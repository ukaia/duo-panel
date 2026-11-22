"""duo-panel-sync: root daemon that keeps the Retroid Pocket Duo's two backlights in step.

Why root: Armada's own root service (armada-control) resets the bottom panel to the value saved in
/etc/armada/bottom-screen-brightness every 2 seconds. An unprivileged app that sets the bottom panel is
undone within 2 s. This daemon therefore keeps that saved value (whole percent) in step with every
change it makes or sees, always writing the file BEFORE the panel, so Armada's check (its rounded
percent equals the saved value) is satisfied and it never writes anything.

The unprivileged app talks to it over /run/duo-panel/control.sock (group armada), JSON lines:
  {"cmd":"get"}
  {"cmd":"set_lock","locked":true}
  {"cmd":"set_trim","trim":-5}            percentage points, bottom minus top
  {"cmd":"set_brightness","screen":"top","pct":55.5}
"""
from __future__ import annotations

import json
import os
import selectors
import shlex
import signal
import socket
import subprocess
import sys
import time
from dataclasses import dataclass

if __package__ in (None, ""):
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from duo_panel.brightness import BOTTOM, SCREENS, TOP, MAX_TRIM, SyncEngine  # noqa: E402


@dataclass
class Paths:
    sys_backlight: str = "/sys/class/backlight"
    saved_bottom: str = "/etc/armada/bottom-screen-brightness"
    config: str = "/var/lib/duo-panel/config.json"
    run_dir: str = "/run/duo-panel"
    device_env: str = "/usr/libexec/armada/device-env"

    @property
    def socket(self):
        return os.path.join(self.run_dir, "control.sock")

    @property
    def state(self):
        return os.path.join(self.run_dir, "state.json")


def atomic_write(path, text, mode=0o644):
    tmp = f"{path}.tmp{os.getpid()}"
    with open(tmp, "w") as f:
        f.write(text)
    os.chmod(tmp, mode)
    os.replace(tmp, path)


def armada_percent(raw, maximum):
    """The exact expression armada-control uses to turn a backlight reading into its saved percent."""
    return max(0, min(100, round(raw * 100 / maximum)))


def discover_backlights(paths):
    """Return {top: name, bottom: name} from Armada's device description, falling back to the two panels found."""
    names = {}
    try:
        out = subprocess.run([paths.device_env], capture_output=True, text=True, timeout=5, check=True).stdout
        env = {}
        for line in out.splitlines():
            key, _, value = line.partition("=")
            env[key] = shlex.split(value)[0] if value else ""
        if env.get("ARMADA_PRIMARY_BACKLIGHT") and env.get("ARMADA_SECONDARY_BACKLIGHT"):
            names = {TOP: env["ARMADA_PRIMARY_BACKLIGHT"], BOTTOM: env["ARMADA_SECONDARY_BACKLIGHT"]}
    except (OSError, subprocess.SubprocessError, ValueError):
        pass
    if not names:
        found = sorted(os.listdir(paths.sys_backlight))
        if len(found) != 2:
            raise RuntimeError(f"expected two backlights, found {found}")
        names = {TOP: found[0], BOTTOM: found[1]}
    return names


class Daemon:
    ACTIVE_POLL = 0.1
    IDLE_POLL = 0.25
    HEARTBEAT = 2.0

    def __init__(self, paths=None, clock=time.monotonic, wall=time.time):
        self.paths = paths or Paths()
        self.clock = clock
        self.wall = wall
        self.names = discover_backlights(self.paths)
        self.max = {s: self._read_int(s, "max_brightness") for s in SCREENS}
        cfg = self._load_config()
        self.engine = SyncEngine(self.max, locked=cfg["locked"], trim=cfg["trim"])
        self.error = None
        self.writes = 0
        self.saved_written = None
        self.last_activity = clock()
        self._state_sig = None
        self._state_at = 0.0
        self.stop = False

    # ---- sysfs ---------------------------------------------------------
    def _file(self, screen, leaf):
        return os.path.join(self.paths.sys_backlight, self.names[screen], leaf)

    def _read_int(self, screen, leaf):
        with open(self._file(screen, leaf)) as f:
            return int(f.read().strip())

    def read_raw(self):
        return {s: self._read_int(s, "brightness") for s in SCREENS}

    def write_panel(self, screen, raw):
        raw = max(0, min(self.max[screen], int(raw)))
        if screen == BOTTOM:
            # Armada's 2-second check compares whole percent with this file: update it first.
            self.save_bottom(armada_percent(raw, self.max[BOTTOM]))
        with open(self._file(screen, "brightness"), "w") as f:
            f.write(f"{raw}\n")
        self.writes += 1

    def save_bottom(self, percent):
        if percent == self.saved_written:
            return
        try:
            atomic_write(self.paths.saved_bottom, f"{percent}\n")
            self.saved_written = percent
        except OSError as error:
            self.error = f"could not save bottom brightness: {error}"

    # ---- config --------------------------------------------------------
    def _load_config(self):
        cfg = {"locked": True, "trim": 0}
        try:
            with open(self.paths.config) as f:
                data = json.load(f)
            if isinstance(data.get("locked"), bool):
                cfg["locked"] = data["locked"]
            if isinstance(data.get("trim"), int) and not isinstance(data["trim"], bool):
                cfg["trim"] = max(-MAX_TRIM, min(MAX_TRIM, data["trim"]))
        except (OSError, ValueError, AttributeError):
            pass
        return cfg

    def _save_config(self):
        try:
            os.makedirs(os.path.dirname(self.paths.config), exist_ok=True)
            atomic_write(self.paths.config, json.dumps({"locked": self.engine.locked, "trim": self.engine.trim}) + "\n")
        except OSError as error:
            self.error = f"could not save config: {error}"

    # ---- main step -----------------------------------------------------
    def tick(self):
        now = self.clock()
        try:
            raw = self.read_raw()
        except (OSError, ValueError) as error:
            self.error = f"backlight read failed: {error}"
            return
        writes = self.engine.step(now, raw)
        if self.engine.bottom_changed:
            # Someone else moved the bottom panel: tell Armada's 2-second check about it BEFORE anything else
            # (including the mirror write below), or it would put the old value back.
            self.last_activity = now
            self.save_bottom(armada_percent(self.engine.last[BOTTOM], self.max[BOTTOM]))
        for write in writes:
            self.last_activity = now
            try:
                self.write_panel(write.screen, write.raw)
                self.error = None
            except OSError as error:
                self.error = f"backlight write failed: {error}"
        self.publish(now)

    def state(self):
        last = self.engine.last or self.read_raw()
        return {
            "ts": round(self.wall(), 1),
            "locked": self.engine.locked,
            "trim": self.engine.trim,
            "last_source": self.engine.last_source,
            "top": {"raw": last[TOP], "max": self.max[TOP], "pct": round(100 * last[TOP] / self.max[TOP], 1)},
            "bottom": {"raw": last[BOTTOM], "max": self.max[BOTTOM], "pct": round(100 * last[BOTTOM] / self.max[BOTTOM], 1)},
            "writes": self.writes,
            "error": self.error,
        }

    def publish(self, now, force=False):
        state = self.state()
        sig = json.dumps({k: v for k, v in state.items() if k != "ts"}, sort_keys=True)
        if force or sig != self._state_sig or now - self._state_at >= self.HEARTBEAT:
            try:
                os.makedirs(self.paths.run_dir, exist_ok=True)
                atomic_write(self.paths.state, json.dumps(state) + "\n", 0o644)
            except OSError:
                return
            self._state_sig, self._state_at = sig, now

    # ---- control socket ------------------------------------------------
    def handle(self, request):
        cmd = request.get("cmd")
        if cmd == "get":
            return {"ok": True, "state": self.state()}
        if cmd == "set_lock":
            locked = request.get("locked")
            if not isinstance(locked, bool):
                return {"ok": False, "error": "locked must be true or false"}
            self.engine.set_locked(locked)
            self._save_config()
        elif cmd == "set_trim":
            trim = request.get("trim")
            if isinstance(trim, bool) or not isinstance(trim, int) or abs(trim) > MAX_TRIM:
                return {"ok": False, "error": f"trim must be a whole number between -{MAX_TRIM} and {MAX_TRIM}"}
            self.engine.set_trim(trim)
            self._save_config()
        elif cmd == "set_brightness":
            screen, pct = request.get("screen"), request.get("pct")
            if screen not in SCREENS:
                return {"ok": False, "error": "screen must be top or bottom"}
            if isinstance(pct, bool) or not isinstance(pct, (int, float)) or not 0 <= pct <= 100:
                return {"ok": False, "error": "pct must be a number from 0 to 100"}
            try:
                self.write_panel(screen, round(pct / 100 * self.max[screen]))
            except OSError as error:
                return {"ok": False, "error": f"write failed: {error}"}
        else:
            return {"ok": False, "error": "unknown command"}
        self.last_activity = self.clock()
        self.publish(self.clock(), force=True)
        return {"ok": True, "state": self.state()}

    def open_socket(self):
        os.makedirs(self.paths.run_dir, exist_ok=True)
        try:
            os.unlink(self.paths.socket)
        except FileNotFoundError:
            pass
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.bind(self.paths.socket)
        try:
            import grp
            os.chown(self.paths.socket, 0, grp.getgrnam("armada").gr_gid)
            os.chmod(self.paths.socket, 0o660)
        except (KeyError, PermissionError, ImportError):
            os.chmod(self.paths.socket, 0o660)
        sock.listen(8)
        sock.setblocking(False)
        return sock

    def serve_client(self, conn):
        with conn:
            conn.settimeout(1.0)
            try:
                data = b""
                while b"\n" not in data and len(data) < 4096:
                    chunk = conn.recv(1024)
                    if not chunk:
                        break
                    data += chunk
                request = json.loads(data.decode() or "null")
                response = self.handle(request) if isinstance(request, dict) else {"ok": False, "error": "bad request"}
            except (ValueError, OSError):
                response = {"ok": False, "error": "bad request"}
            try:
                conn.sendall((json.dumps(response) + "\n").encode())
            except OSError:
                pass

    def run(self):
        sock = self.open_socket()
        selector = selectors.DefaultSelector()
        selector.register(sock, selectors.EVENT_READ)
        signal.signal(signal.SIGTERM, lambda *_: setattr(self, "stop", True))
        signal.signal(signal.SIGINT, lambda *_: setattr(self, "stop", True))
        self.publish(self.clock(), force=True)
        while not self.stop:
            self.tick()
            idle = self.clock() - self.last_activity > 5
            for key, _ in selector.select(self.IDLE_POLL if idle else self.ACTIVE_POLL):
                conn, _ = key.fileobj.accept()
                self.serve_client(conn)
        for leaf in (self.paths.socket, self.paths.state):
            try:
                os.unlink(leaf)
            except FileNotFoundError:
                pass


def main():
    Daemon().run()


if __name__ == "__main__":
    main()
