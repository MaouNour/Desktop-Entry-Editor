#!/usr/bin/env bash
set -euo pipefail

APP_ID="io.github.desktopentryeditor.Editor"
SHARE_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/desktop-entry-editor"
BIN_DIR="${XDG_BIN_HOME:-$HOME/.local/bin}"
APPS_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
ICON_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor/scalable/apps"

rm -rf "$SHARE_DIR"
rm -f "$BIN_DIR/desktop-entry-editor"
rm -f "$APPS_DIR/$APP_ID.desktop"
rm -f "$ICON_DIR/$APP_ID.svg"

command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$APPS_DIR" || true

echo "Uninstalled."
