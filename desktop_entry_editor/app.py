import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, Gio, GLib

from .window import MainWindow

APPLICATION_ID = "io.github.desktopentryeditor.Editor"


class DesktopEntryEditorApp(Adw.Application):
    """A GApplication with HANDLES_OPEN so it works both when double
    clicked on a .desktop file (Exec=... %f/%u) and when invoked from a
    terminal as `desktop-entry-editor /path/to/file.desktop`."""

    def __init__(self):
        super().__init__(
            application_id=APPLICATION_ID,
            flags=Gio.ApplicationFlags.HANDLES_OPEN,
        )
        self._window: MainWindow | None = None

    def do_activate(self):
        if self._window is None:
            self._window = MainWindow(self)
        self._window.present()

    def do_open(self, files, n_files, hint):
        if self._window is None:
            path = files[0].get_path() if n_files > 0 else None
            self._window = MainWindow(self, path=path)
        else:
            if n_files > 0:
                self._window.load_path(files[0].get_path())
            self._window.present()

        # Any additional files beyond the first each get their own window.
        for gfile in list(files)[1:]:
            win = MainWindow(self, path=gfile.get_path())
            win.present()

        self._window.present()


def main(argv=None):
    app = DesktopEntryEditorApp()
    import sys
    return app.run(argv if argv is not None else sys.argv)
