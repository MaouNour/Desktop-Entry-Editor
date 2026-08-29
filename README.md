# Desktop Entry Editor

A native GTK4 + libadwaita application for creating and editing Linux
`.desktop` (and `.directory`) files, implementing the full
[freedesktop.org Desktop Entry Specification](https://specifications.freedesktop.org/desktop-entry-spec/latest/).

## Features

- **All standard keys**: Type, Name, GenericName, Comment, Icon, Version,
  NoDisplay, Hidden, Exec, TryExec, Path, Terminal, StartupNotify,
  StartupWMClass, DBusActivatable, SingleMainWindow, PrefersNonDefaultGPU,
  URL, MimeType, Categories, Keywords, Implements, OnlyShowIn, NotShowIn.
- **Custom Actions** (`[Desktop Action X]` sections) — add, rename, reorder
  (via the `Actions=` list) and delete right-click menu actions, each with
  its own Name/Icon/Exec.
- **Full localization support** — every `Name[fr]`, `Comment[de_DE]`,
  `Keywords[es]`-style variant can be added/edited/removed per key via the
  🌐 button next to translatable fields.
- **Icon picker** with a live preview, supporting both icon-theme names
  (`firefox`) and absolute file paths.
- **Category picker** with checkboxes for every registered Main and
  Additional category from the spec, plus a field for custom/unlisted ones.
- **Raw source view** — see and hand-edit the literal file text, with
  Apply/Revert.
- **Preserves formatting** — comments and blank lines in a loaded file are
  kept as-is when you save, and unrelated key order is preserved.
- **Test-run button** to sanity check the `Exec=` command actually launches.
- Opens by **double-clicking a `.desktop` file** in your file manager, or by
  running `desktop-entry-editor /path/to/file.desktop` from a terminal.

## Dependencies

- Python 3.10+
- PyGObject (`python3-gi`)
- GTK 4.10+ (for `Gtk.FileDialog`)
- libadwaita 1.4+ (for `Adw.SwitchRow`, `Adw.EntryRow`, etc.)

Install the system packages first:

```bash
# Debian / Ubuntu
sudo apt install python3-gi gir1.2-gtk-4.0 gir1.2-adw-1

# Fedora
sudo dnf install python3-gobject gtk4 libadwaita

# Arch
sudo pacman -S python-gobject gtk4 libadwaita
```

## Install

```bash
./install.sh
```

This installs everything under your home directory (no root needed):

- App code → `~/.local/share/desktop-entry-editor/`
- Launcher script → `~/.local/bin/desktop-entry-editor`
- `.desktop` file → `~/.local/share/applications/`
- Icon → `~/.local/share/icons/hicolor/scalable/apps/`

To uninstall: `./uninstall.sh`

## Usage

```bash
desktop-entry-editor                       # start with a blank new entry
desktop-entry-editor mytool.desktop        # open an existing file
```

Or just double-click any `.desktop` file and pick **Desktop Entry Editor**
from "Open With". To make it the default handler for `.desktop` files:

```bash
xdg-mime default io.github.desktopentryeditor.Editor.desktop application/x-desktop
```

## Running without installing

```bash
python3 main.py [optional/path/to/file.desktop]
```

## Project layout

```
main.py                          entry point
desktop_entry_editor/
  desktop_entry.py               spec-compliant parser/writer (no GTK dependency)
  app.py                         Adw.Application (handles activation + file-open)
  window.py                      main window, all editing pages
  icon_row.py                    Icon= picker widget with preview
  localization_dialog.py         per-locale editing dialog
data/
  *.desktop, *.svg               the app's own launcher + icon, for installing
install.sh / uninstall.sh
tests/sample.desktop             a sample file exercising most spec features
```

## Notes / limitations

- Value escaping follows the spec's basic rules (`\\`, `\n`, `\t`, `\r`,
  `\;`); some exotic edge cases may format slightly differently on
  round-trip, but standard files parse and re-save losslessly.
- The category checkbox UI re-sorts categories using the spec's own Main →
  Additional order when you toggle any checkbox; hand-edit the "Source" tab
  if you need to preserve a specific custom order.
