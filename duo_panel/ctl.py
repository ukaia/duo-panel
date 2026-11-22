"""Client for the duo-panel-sync control socket (used by the app and by `python -m duo_panel.ctl`)."""
from __future__ import annotations

import json
import os
import socket
import sys

SOCKET = "/run/duo-panel/control.sock"
STATE = "/run/duo-panel/state.json"


def request(payload, path=SOCKET, timeout=1.5):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
        s.settimeout(timeout)
        s.connect(path)
        s.sendall((json.dumps(payload) + "\n").encode())
        data = b""
        while b"\n" not in data:
            chunk = s.recv(4096)
            if not chunk:
                break
            data += chunk
    return json.loads(data.decode())


def read_state(path=STATE):
    """Latest published state, or None when the daemon is not running."""
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def main(argv):
    usage = "usage: ctl get | lock on|off | trim N | set top|bottom PCT"
    try:
        if argv[:1] == ["get"]:
            payload = {"cmd": "get"}
        elif argv[:1] == ["lock"] and len(argv) == 2 and argv[1] in ("on", "off"):
            payload = {"cmd": "set_lock", "locked": argv[1] == "on"}
        elif argv[:1] == ["trim"] and len(argv) == 2:
            payload = {"cmd": "set_trim", "trim": int(argv[1])}
        elif argv[:1] == ["set"] and len(argv) == 3:
            payload = {"cmd": "set_brightness", "screen": argv[1], "pct": float(argv[2])}
        else:
            print(usage)
            return 2
        print(json.dumps(request(payload), indent=1))
        return 0
    except (OSError, ValueError) as error:
        print(f"ctl: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
