import os
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, Gio, GObject, GLib


class IconEntryRow(Adw.EntryRow):
    """An Adw.EntryRow specialised for picking an Icon= value: shows a live
    preview (themed icon name or absolute file path) and a browse button."""

    __gsignals__ = {
        "value-changed": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
    }

    def __init__(self, title="Icon"):
        super().__init__(title=title)
        self._updating = False

        self._preview = Gtk.Image()
        self._preview.set_pixel_size(32)
        self._preview.add_css_class("icon-dropshadow")
        self.add_prefix(self._preview)

        browse = Gtk.Button(icon_name="folder-open-symbolic", valign=Gtk.Align.CENTER)
        browse.set_tooltip_text("Browse for an icon file")
        browse.add_css_class("flat")
        browse.connect("clicked", self._on_browse)
        self.add_suffix(browse)

        self.connect("changed", self._on_changed)

    def set_value(self, value: str):
        self._updating = True
        self.set_text(value or "")
        self._updating = False
        self._update_preview(value or "")

    def _on_changed(self, *_a):
        text = self.get_text()
        self._update_preview(text)
        if not self._updating:
            self.emit("value-changed", text)

    def _update_preview(self, value: str):
        if not value:
            self._preview.set_from_icon_name("image-missing-symbolic")
            return
        if os.path.isabs(value) or value.startswith("~") or "/" in value:
            path = os.path.expanduser(value)
            if os.path.exists(path):
                self._preview.set_from_file(path)
            else:
                self._preview.set_from_icon_name("image-missing-symbolic")
        else:
            self._preview.set_from_icon_name(value)

    def _on_browse(self, *_a):
        dialog = Gtk.FileDialog(title="Choose Icon File")
        filt = Gtk.FileFilter()
        filt.set_name("Images")
        filt.add_mime_type("image/png")
        filt.add_mime_type("image/svg+xml")
        filt.add_mime_type("image/x-xpixmap")
        filt.add_pattern("*.png")
        filt.add_pattern("*.svg")
        filt.add_pattern("*.xpm")
        store = Gio.ListStore.new(Gtk.FileFilter)
        store.append(filt)
        dialog.set_filters(store)

        root = self.get_root()

        def on_done(dlg, result):
            try:
                gfile = dlg.open_finish(result)
            except GLib.Error:
                return
            if gfile:
                self.set_value(gfile.get_path())
                self.emit("value-changed", gfile.get_path())

        dialog.open(root, None, on_done)
