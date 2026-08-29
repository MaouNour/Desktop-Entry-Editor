#!/usr/bin/env bash
# Installs Desktop Entry Editor for the current user (no root required).
set -euo pipefail

APP_ID="io.github.desktopentryeditor.Editor"
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

SHARE_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/desktop-entry-editor"
BIN_DIR="${XDG_BIN_HOME:-$HOME/.local/bin}"
APPS_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
ICON_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor/scalable/apps"

echo "==> Checking dependencies"
if ! python3 -c "import gi; gi.require_version('Gtk','4.0'); gi.require_version('Adw','1'); from gi.repository import Gtk, Adw" 2>/dev/null; then
    echo "Missing PyGObject / GTK4 / libadwaita bindings for Python 3."
    echo "Install them first, e.g. on Debian/Ubuntu:"
    echo "    sudo apt install python3-gi gir1.2-gtk-4.0 gir1.2-adw-1"
    echo "or on Fedora:"
    echo "    sudo dnf install python3-gobject gtk4 libadwaita"
    echo "or on Arch:"
    echo "    sudo pacman -S python-gobject gtk4 libadwaita"
    exit 1
fi
echo "    OK"

echo "==> Installing application files to $SHARE_DIR"
mkdir -p "$SHARE_DIR"
cp -r "$SRC_DIR/main.py" "$SRC_DIR/desktop_entry_editor" "$SHARE_DIR/"

echo "==> Installing launcher to $BIN_DIR/desktop-entry-editor"
mkdir -p "$BIN_DIR"
cat > "$BIN_DIR/desktop-entry-editor" <<EOF
#!/usr/bin/env bash
exec python3 "$SHARE_DIR/main.py" "\$@"
EOF
chmod +x "$BIN_DIR/desktop-entry-editor"

echo "==> Installing .desktop launcher to $APPS_DIR"
mkdir -p "$APPS_DIR"
cp "$SRC_DIR/data/$APP_ID.desktop" "$APPS_DIR/"

echo "==> Installing icon to $ICON_DIR"
mkdir -p "$ICON_DIR"
cp "$SRC_DIR/data/$APP_ID.svg" "$ICON_DIR/"

echo "==> Updating caches"
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$APPS_DIR" || true
command -v gtk-update-icon-cache >/dev/null 2>&1 && gtk-update-icon-cache -f -t "${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor" 2>/dev/null || true

case ":$PATH:" in
    *":$BIN_DIR:"*) ;;
    *) echo "NOTE: $BIN_DIR is not on your PATH. Add this to your shell profile:"
       echo "    export PATH=\"$BIN_DIR:\$PATH\"" ;;
esac

echo ""
echo "Installed! You can now:"
echo "  - Run 'desktop-entry-editor' from a terminal"
echo "  - Run 'desktop-entry-editor /path/to/file.desktop' to open a file directly"
echo "  - Double-click any .desktop file and choose 'Desktop Entry Editor', or"
echo "    right-click -> Open With -> Desktop Entry Editor"
echo "  - Find it in your application launcher as 'Desktop Entry Editor'"
echo ""
echo "To make it the default handler for .desktop files, run:"
echo "    xdg-mime default $APP_ID.desktop application/x-desktop"
