#!/bin/bash
# Renders the app on the Duo with Qt's offscreen platform (nothing appears on either screen) and copies the PNG back.
# Usage: DUO=user@host deploy/shot.sh out.png --theme steamdeck [--demo fixtures/demo.json]      (DUO defaults to the ssh alias "retroid")
set -euo pipefail
out=$1; shift
DUO=${DUO:-retroid}
cd "$(dirname "$0")/.."
rm -rf duo_panel/__pycache__
COPYFILE_DISABLE=1 tar --no-xattrs -cf - duo_panel fixtures | ssh -o BatchMode=yes "$DUO" 'rm -rf ~/duo-panel-ui && mkdir -p ~/duo-panel-ui && tar -xf - -C ~/duo-panel-ui'
ssh -o BatchMode=yes "$DUO" "cd ~/duo-panel-ui && QT_QPA_PLATFORM=offscreen QT_QUICK_BACKEND=software QT_QUICK_CONTROLS_STYLE=Basic timeout 90 python3 -m duo_panel.app --windowed --screenshot /tmp/shot.png --delay 5 $* 2>&1 | head -30"
scp -q "$DUO":/tmp/shot.png "$out" && echo "copied $out"
