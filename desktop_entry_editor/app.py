import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, Gio, GLib

from .window import MainWindow
from .browser import BrowserWindow

APPLICATION_ID = "io.github.desktopentryeditor.Editor"


class DesktopEntryEditorApp(Adw.Application):
    """A GApplication with HANDLES_OPEN so it works both when double
    clicked on a .desktop file (Exec=... %f/%u) and when invoked from a
    terminal as `desktop-entry-editor /path/to/file.desktop`.

    Two kinds of top-level windows are managed here:
      - a single BrowserWindow that lets you navigate every desktop
        entry on the system by category / search
      - any number of MainWindow editors, one per file currently being
        edited (kept in a registry so opening the same path twice just
        re-presents the existing editor instead of duplicating it)
    """

    def __init__(self):
        super().__init__(
            application_id=APPLICATION_ID,
            flags=Gio.ApplicationFlags.HANDLES_OPEN,
        )
        self._browser: BrowserWindow | None = None
        self._editors: list[MainWindow] = []

    # ------------------------------------------------------------------
    # GApplication entry points
    # ------------------------------------------------------------------
    def do_activate(self):
        # Launched with no file argument: show the browser (old
        # behaviour of opening a blank new entry is still one click
        # away via the browser's "New" button).
        if self._browser is None and not self._editors:
            self.show_browser()
        elif self._browser is not None:
            self._browser.present()
        else:
            self._editors[-1].present()

    def do_open(self, files, n_files, hint):
        # Double-clicking a .desktop file, or `desktop-entry-editor
        # FILE.desktop` from a terminal, always jumps straight into the
        # editor for that file -- the classic single-file workflow is
        # untouched.
        for gfile in files:
            self.open_editor_for_path(gfile.get_path())

    # ------------------------------------------------------------------
    # Window management
    # ------------------------------------------------------------------
    def show_browser(self, refresh: bool = False):
        if self._browser is None:
            self._browser = BrowserWindow(self)
            self._browser.connect("destroy", self._on_browser_destroyed)
        elif refresh:
            self._browser.refresh()
        self._browser.present()
        return self._browser

    def _on_browser_destroyed(self, *_a):
        self._browser = None

    def open_editor_for_path(self, path: str | None):
        """Open `path` for editing, reusing an already-open editor
        window for that same file if there is one. path=None opens a
        fresh blank entry (always a new window)."""
        if path:
            for win in self._editors:
                if win.current_path == path:
                    win.present()
                    return win

        win = MainWindow(self, path=path)
        self._editors.append(win)
        win.connect("destroy", lambda *_a, w=win: self._editors.remove(w) if w in self._editors else None)
        win.present()
        return win


def main(argv=None):
    app = DesktopEntryEditorApp()
    import sys
    return app.run(argv if argv is not None else sys.argv)
