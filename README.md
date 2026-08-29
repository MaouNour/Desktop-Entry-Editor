# Desktop Entry Editor

A native GTK4 + libadwaita application for creating and editing Linux
`.desktop` (and `.directory`) files, implementing the full
[freedesktop.org Desktop Entry Specification](https://specifications.freedesktop.org/desktop-entry-spec/latest/).

## Features

- **Browse every entry on your system.** Launching the app with no file
  argument opens a Browser window that scans `~/.local/share/applications`,
  every directory in `XDG_DATA_DIRS` (e.g. `/usr/share/applications`),
  and the common Flatpak/Snap export locations — then lists them grouped
  by category (with search) so you don't have to know a file's path to
  edit it. User copies correctly shadow/override system entries with the
  same id, matching how the desktop shell itself resolves them.
- **Install new entries with one click.** The header bar's "+" (Install)
  button saves the current entry straight to
  `~/.local/share/applications/<Name>.desktop` — no file-picker required —
  so a brand-new launcher shows up in your Applications menu immediately.
- **Old-style single-file editing is untouched.** `main.py FILE.desktop`,
  double-click-to-open, Save/Save As to any path you choose, and the raw
  Source tab all work exactly as before — the Browser is purely additive.
- **Graceful handling of read-only system entries.** If you open a system
  file (e.g. under `/usr/share/applications`) and hit Save, and you don't
  have permission to overwrite it in place, the app offers to save your
  edited copy into your user Applications folder instead — the standard
  way of overriding a system launcher without root.
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
desktop-entry-editor                       # open the Browser (all entries, by category)
desktop-entry-editor mytool.desktop        # open an existing file directly in the editor
```

In the Browser: pick a category on the left (or search), click any entry
to open it in the editor, or click "+" in the header to start a blank one.
In the editor: the grid icon in the header takes you back to the Browser
at any time; Save/Save As behave as always, and the new "+" (Install)
button is the fast path for saving a new or edited entry into your
personal Applications menu.

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
  scanner.py                     finds/indexes every .desktop file on the system (no GTK dependency)
  app.py                         Adw.Application (browser + editor window management, file-open)
  browser.py                     Browser window: category sidebar, search, entry list
  window.py                      editor window, all editing pages
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
