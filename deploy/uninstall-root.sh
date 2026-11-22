#!/bin/bash
# Removes the duo-panel-sync root service and gives Armada back its own bottom-screen brightness handling.
# Usage: sudo bash /var/lib/duo-panel/uninstall-root.sh [--keep-brightness]
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo "run as root" >&2; exit 1; }
systemctl disable --now duo-panel-sync.service 2>/dev/null || true
rm -f /etc/systemd/system/duo-panel-sync.service
systemctl daemon-reload
# Armada keeps enforcing whatever percent is in /etc/armada/bottom-screen-brightness; the value the service last
# saved is a valid one, so it is left alone unless you ask for the original back.
if [[ ${1:-} != --keep-brightness && -f /var/lib/duo-panel/bottom-screen-brightness.before ]]; then
    cp /var/lib/duo-panel/bottom-screen-brightness.before /etc/armada/bottom-screen-brightness
    echo "restored Armada's original saved bottom brightness: $(cat /etc/armada/bottom-screen-brightness)"
fi
rm -rf /var/lib/duo-panel
echo "duo-panel-sync removed"
