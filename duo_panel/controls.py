"""Toggles and settings the Duo panel can change, using the same supported routes Armada itself uses.

Every external command goes through `run(argv, timeout) -> (returncode, stdout)` so the tests can fake it."""
from __future__ import annotations

import os
import re
import subprocess

PROFILES = ["Eco", "Balanced", "Performance"]
SYNCTHING_HOME = os.path.expanduser("~/.local/state/syncthing")


def default_run(argv, timeout=8):
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout or "") + ("" if p.returncode == 0 else (p.stderr or ""))
    except (OSError, subprocess.SubprocessError) as error:
        return 127, str(error)


def split_nmcli(line):
    """Split an `nmcli -t` line on unescaped colons."""
    return [part.replace("\\:", ":").replace("\\\\", "\\") for part in re.split(r"(?<!\\):", line)]


class Controls:
    def __init__(self, run=default_run, syncthing_api=None):
        self.run = run
        self.syncthing_api = syncthing_api   # callable() -> connected device count or None

    # ---- reading -------------------------------------------------------
    def read_states(self):
        return {"wifi": self.wifi(), "bluetooth": self.bluetooth(), "syncthing": self.syncthing(),
                "ssh": self.ssh(), "profile": self.profile()}

    def wifi(self):
        rc, out = self.run(["nmcli", "radio", "wifi"])
        enabled = rc == 0 and out.strip() == "enabled"
        ssid, signal = None, None
        if enabled:
            rc, out = self.run(["nmcli", "-t", "-f", "IN-USE,SSID,SIGNAL", "dev", "wifi", "list", "--rescan", "no"])
            if rc == 0:
                for line in out.splitlines():
                    parts = split_nmcli(line)
                    if len(parts) >= 3 and parts[0] == "*":
                        ssid = parts[1] or None
                        signal = int(parts[2]) if parts[2].isdigit() else None
                        break
        return {"enabled": enabled, "ssid": ssid, "signal": signal}

    def bluetooth(self):
        rc, out = self.run(["bluetoothctl", "show"])
        if rc != 0:
            return {"available": False, "powered": False}
        m = re.search(r"Powered:\s*(yes|no)", out)
        return {"available": True, "powered": bool(m and m.group(1) == "yes")}

    def syncthing(self):
        rc, out = self.run(["systemctl", "--user", "is-active", "syncthing.service"])
        active = out.strip() == "active"
        devices = None
        if active and self.syncthing_api:
            try:
                devices = self.syncthing_api()
            except Exception:
                devices = None
        return {"active": active, "connected": devices}

    def ssh(self):
        rc, out = self.run(["systemctl", "is-active", "sshd"])
        return {"active": out.strip() == "active"}

    def profile(self):
        rc, out = self.run(["armada-power", "profile"])
        name = out.strip().splitlines()[0] if rc == 0 and out.strip() else None
        return {"name": name, "options": PROFILES}

    # ---- changing ------------------------------------------------------
    def set_wifi(self, on):
        return self._do(["nmcli", "radio", "wifi", "on" if on else "off"])

    def set_bluetooth(self, on):
        return self._do(["bluetoothctl", "power", "on" if on else "off"])

    def set_syncthing(self, on):
        return self._do(["systemctl", "--user", "start" if on else "stop", "syncthing.service"])

    def set_ssh(self, on):
        return self._do(["pkexec", "--disable-internal-agent", "/usr/libexec/armada/armada-tools-priv",
                         "enable-ssh" if on else "disable-ssh"])

    def set_profile(self, name):
        if name not in PROFILES:
            return False, f"unknown profile {name!r}"
        return self._do(["armada-power", "profile", name])

    def _do(self, argv):
        rc, out = self.run(argv)
        return rc == 0, (out or "").strip().splitlines()[-1] if out and out.strip() else ""

    ACTIONS = {"wifi": "set_wifi", "bluetooth": "set_bluetooth", "syncthing": "set_syncthing", "ssh": "set_ssh"}

    def toggle(self, name, on):
        method = self.ACTIONS.get(name)
        if not method:
            return False, f"unknown toggle {name!r}"
        return getattr(self, method)(bool(on))


def syncthing_connected_count(home=SYNCTHING_HOME, urlopen=None):
    """How many remote devices Syncthing reports as connected (local REST API; the API key never leaves this function)."""
    import json
    import urllib.request
    try:
        with open(os.path.join(home, "config.xml")) as f:
            key = re.search(r"<apikey>([^<]+)</apikey>", f.read()).group(1)
    except (OSError, AttributeError):
        return None
    req = urllib.request.Request("http://127.0.0.1:8384/rest/system/connections", headers={"X-API-Key": key})
    with (urlopen or urllib.request.urlopen)(req, timeout=2) as resp:
        data = json.load(resp)
    return sum(1 for c in data.get("connections", {}).values() if c.get("connected"))
