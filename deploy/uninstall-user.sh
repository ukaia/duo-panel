#!/bin/bash
# Removes what install-user.sh put in the home directory. The root brightness service has its own uninstall-root.sh.
rm -rf "$HOME/.local/share/duo-panel" "$HOME/.local/bin/duo-panel" "$HOME/.local/share/applications/duo-panel.desktop" "$HOME/.config/duo-panel"
find "$HOME/.local/share/icons/hicolor" -name 'duo-panel.*' -delete 2>/dev/null
update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true
echo removed
