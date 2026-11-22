#!/bin/bash
# Installs the duo-panel-sync root service from a staging folder. Run as root from the repo checkout: sudo bash deploy/install-root.sh [repo-dir]
# Rollback: sudo bash /var/lib/duo-panel/uninstall-root.sh
set -euo pipefail
STAGE=${1:-$(cd "$(dirname "$0")/.." && pwd)}
DEST=/var/lib/duo-panel

[[ $EUID -eq 0 ]] || { echo "run as root" >&2; exit 1; }
for f in __init__.py brightness.py syncd.py ctl.py; do [[ -f $STAGE/duo_panel/$f ]] || { echo "missing $STAGE/duo_panel/$f" >&2; exit 1; }; done

install -d -m 755 -o root -g root "$DEST" "$DEST/duo_panel"
# Rollback record of what Armada had saved before this service ever touched it.
if [[ -f /etc/armada/bottom-screen-brightness && ! -f $DEST/bottom-screen-brightness.before ]]; then
    cp -a /etc/armada/bottom-screen-brightness "$DEST/bottom-screen-brightness.before"
fi
for f in __init__.py brightness.py syncd.py ctl.py; do
    install -m 644 -o root -g root "$STAGE/duo_panel/$f" "$DEST/duo_panel/$f"
done
install -m 644 -o root -g root "$STAGE/README.md" "$DEST/README.md"
install -m 755 -o root -g root "$STAGE/deploy/uninstall-root.sh" "$DEST/uninstall-root.sh"
install -m 644 -o root -g root "$STAGE/deploy/duo-panel-sync.service" /etc/systemd/system/duo-panel-sync.service

python3 - <<'PY'
import ast, sys
for f in ("brightness", "syncd", "ctl"):
    ast.parse(open(f"/var/lib/duo-panel/duo_panel/{f}.py").read())
print("syntax ok")
PY
systemctl daemon-reload
systemctl enable --now duo-panel-sync.service
sleep 2
systemctl is-active duo-panel-sync.service
echo "installed to $DEST; saved bottom value before: $(cat $DEST/bottom-screen-brightness.before 2>/dev/null || echo none)"
