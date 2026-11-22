#!/bin/bash
# Installs the Duo Panel UI for the current user (no root). Run on the Duo from the repo checkout:  bash deploy/install-user.sh
set -euo pipefail
here=$(cd "$(dirname "$0")/.." && pwd)
dest=$HOME/.local/share/duo-panel
mkdir -p "$dest" "$HOME/.local/bin" "$HOME/.local/share/applications" "$HOME/.local/share/icons/hicolor/scalable/apps"
rm -rf "$dest/duo_panel"
cp -r "$here/duo_panel" "$dest/duo_panel"
find "$dest" -name __pycache__ -prune -exec rm -rf {} +
cat > "$HOME/.local/bin/duo-panel" <<'EOF'
#!/bin/bash
# Launcher for the Duo Panel: opens on whichever screen the calling session draws on (the bottom desktop's app drawer).
cd "$HOME/.local/share/duo-panel" && exec python3 -m duo_panel.app "$@"
EOF
chmod +x "$HOME/.local/bin/duo-panel"
cp "$here/deploy/icons/duo-panel.svg" "$HOME/.local/share/icons/hicolor/scalable/apps/duo-panel.svg" 2>/dev/null || cp "$here/deploy/duo-panel.svg" "$HOME/.local/share/icons/hicolor/scalable/apps/duo-panel.svg"
for n in 64 128 256 512; do
  mkdir -p "$HOME/.local/share/icons/hicolor/${n}x${n}/apps"
  cp "$here/deploy/icons/duo-panel-$n.png" "$HOME/.local/share/icons/hicolor/${n}x${n}/apps/duo-panel.png"
done
# Armada's own launcher entries use an absolute icon path (the bottom shell's drawer shows those reliably), so do the same.
sed -e "s|^Exec=.*|Exec=$HOME/.local/bin/duo-panel|" -e "s|^Icon=.*|Icon=$HOME/.local/share/icons/hicolor/128x128/apps/duo-panel.png|" \
    "$here/deploy/duo-panel.desktop" > "$HOME/.local/share/applications/duo-panel.desktop"
update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true
gtk-update-icon-cache -q "$HOME/.local/share/icons/hicolor" 2>/dev/null || true
echo "installed: $HOME/.local/bin/duo-panel, $dest, desktop entry + icons"
