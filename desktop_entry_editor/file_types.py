"""
file_types.py

The "File Types" page: every file suffix the system knows about (.exe,
.tar.xz, .pdf, ...) grouped by MIME type, each showing which application
currently opens it. Click a row to pick a different one or reset it.

Search understands suffixes ("exe", ".tar.xz", "*.txz"), MIME types
("x-xz") and descriptions ("archive"). Exact suffix matches sort first.
"""
from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, GLib, Pango

from . import mimeapps as ma

_MAX_SUFFIXES_IN_TITLE = 4


class _AppChooserDialog(Adw.Window):
    """Modal dialog: choose which app opens one MIME type."""

    def __init__(self, parent, mime: str, suffixes: list[str], on_changed):
        super().__init__(transient_for=parent, modal=True,
                         default_width=440, default_height=600)
        self.mime = mime
        self._on_changed = on_changed
        self._apps: list = []
        self._building = False
        self._group_first: Gtk.CheckButton | None = None

        label = ", ".join("." + s for s in suffixes[:_MAX_SUFFIXES_IN_TITLE]) or mime
        self.set_title(f"Open {label} with…")

        view = Adw.ToolbarView()
        header = Adw.HeaderBar()
        self.reset_btn = Gtk.Button(label="Reset", tooltip_text="Go back to the system default")
        self.reset_btn.connect("clicked", self._on_reset)
        header.pack_start(self.reset_btn)
        view.add_top_bar(header)

        page = Adw.PreferencesPage()

        info = Adw.PreferencesGroup(title=GLib.markup_escape_text(ma.describe(mime)),
                                    description=GLib.markup_escape_text(mime))
        self.show_all = Adw.SwitchRow(
            title="Show all applications",
            subtitle="Include apps that don't say they support this type")
        self.show_all.connect("notify::active", lambda *_: self._rebuild())
        info.add(self.show_all)
        page.add(info)

        self.apps_group = Adw.PreferencesGroup(title="Applications")
        page.add(self.apps_group)
        self._app_rows: list[Gtk.Widget] = []

        view.set_content(page)
        self.set_content(view)

        # Escape closes the dialog (Adw.Window doesn't do this by itself).
        esc = Gtk.ShortcutController()
        esc.add_shortcut(Gtk.Shortcut.new(
            Gtk.ShortcutTrigger.parse_string("Escape"),
            Gtk.CallbackAction.new(lambda *_: self.close() or True)))
        self.add_controller(esc)

        self._rebuild()

    # ------------------------------------------------------------------
    def _rebuild(self):
        for row in self._app_rows:
            self.apps_group.remove(row)
        self._app_rows.clear()
        self._group_first = None

        current = ma.get_default(self.mime)
        cur_id = ma.app_id(current)
        self._apps = ma.candidates_for(self.mime, include_all=self.show_all.get_active())

        self._building = True
        try:
            if not self._apps:
                row = Adw.ActionRow(
                    title="No application found",
                    subtitle="Turn on “Show all applications” to pick any installed app.")
                row.set_sensitive(False)
                self.apps_group.add(row)
                self._app_rows.append(row)
            for app in self._apps:
                row = Adw.ActionRow(title=GLib.markup_escape_text(ma.app_name(app)))
                row.set_activatable(True)
                gicon = app.get_icon()
                if gicon is not None:
                    row.add_prefix(Gtk.Image(gicon=gicon, pixel_size=32))
                check = Gtk.CheckButton(valign=Gtk.Align.CENTER)
                if self._group_first is None:
                    self._group_first = check
                else:
                    check.set_group(self._group_first)
                check.set_active(ma.app_id(app) == cur_id)
                check.connect("toggled", self._on_toggled, app)
                row.add_suffix(check)
                row.set_activatable_widget(check)
                self.apps_group.add(row)
                self._app_rows.append(row)
        finally:
            self._building = False

        self.reset_btn.set_sensitive(self.mime in ma.user_customized_types())

    def _on_toggled(self, check, app):
        if self._building or not check.get_active():
            return
        errors = ma.set_default(app, [self.mime])
        if errors:
            self._on_changed(f"Could not change default: {errors[0]}")
        else:
            self._on_changed(f"{ma.describe(self.mime)}: {ma.app_name(app)}")
        self.reset_btn.set_sensitive(self.mime in ma.user_customized_types())

    def _on_reset(self, *_a):
        errors = ma.reset_defaults([self.mime])
        self._on_changed(f"Could not reset: {errors[0]}" if errors
                         else f"{ma.describe(self.mime)}: back to system default")
        self._rebuild()


class _TypeRow(Adw.ActionRow):
    def __init__(self, mime: str, suffixes: list[str]):
        super().__init__()
        self.mime = mime
        self.suffixes = suffixes
        self.description = ma.describe(mime)
        self.set_activatable(True)

        shown = suffixes[:_MAX_SUFFIXES_IN_TITLE]
        title = ", ".join("." + s for s in shown) if shown else mime
        if len(suffixes) > len(shown):
            title += " …"
        self.set_title(GLib.markup_escape_text(title))
        self.set_subtitle(GLib.markup_escape_text(
            self.description if not shown else f"{self.description} — {mime}"))
        self.sort_key = suffixes[0] if suffixes else mime

        self.app_label = Gtk.Label(ellipsize=Pango.EllipsizeMode.END, max_width_chars=28)
        self.app_label.add_css_class("dim-label")
        self.add_suffix(self.app_label)
        self.add_suffix(Gtk.Image(icon_name="go-next-symbolic"))
        self.update_default()

    def update_default(self):
        app = ma.get_default(self.mime)
        self.app_label.set_text(ma.app_name(app) if app is not None else "No default")

    def matches(self, q: str) -> bool:
        if not q:
            return True
        return (any(q in s for s in self.suffixes)
                or q in self.mime.lower()
                or q in self.description.lower())

    def rank(self, q: str) -> int:
        if q:
            if q in self.suffixes:
                return 0
            if any(s.startswith(q) for s in self.suffixes):
                return 1
            if any(q in s for s in self.suffixes):
                return 2
        return 3


class FileTypesPage(Adw.Bin):
    """Search/browse file suffixes and change what opens them."""

    def __init__(self, on_toast=None):
        super().__init__()
        self._on_toast = on_toast or (lambda _msg: None)
        self._query = ""
        self._only_changed = False
        self._customized: set[str] = set()
        self._built = False
        self._build_token = None

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        top = Gtk.Box(spacing=12, margin_top=12, margin_start=12, margin_end=12)
        self.search = Gtk.SearchEntry(
            hexpand=True, placeholder_text="Search a suffix (exe, tar.xz…), type or description")
        self.search.connect("search-changed", self._on_search_changed)
        top.append(self.search)
        self.only_changed = Gtk.CheckButton(label="Only ones I changed")
        self.only_changed.connect("toggled", self._on_only_changed)
        top.append(self.only_changed)
        box.append(top)

        self.list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.list.add_css_class("boxed-list")
        self.list.set_margin_top(12)
        self.list.set_margin_bottom(12)
        self.list.set_margin_start(12)
        self.list.set_margin_end(12)
        self.list.set_filter_func(self._filter)
        self.list.set_sort_func(self._sort)
        self.list.connect("row-activated", self._on_row_activated)
        scroller = Gtk.ScrolledWindow(child=self.list, vexpand=True)

        self.empty = Adw.StatusPage(
            title="No File Types Found", icon_name="edit-find-symbolic",
            description="Try another suffix, e.g. “pdf” or “tar.gz”.")

        self.stack = Gtk.Stack(vexpand=True)
        self.stack.add_child(scroller)
        self.stack.add_child(self.empty)
        self.stack.set_visible_child(scroller)
        self._scroller = scroller
        box.append(self.stack)
        self.set_child(box)

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------
    def refresh(self):
        """Called whenever the page is shown. First call builds the list
        (in small batches so the window never freezes); later calls just
        re-read which app is the default for each row."""
        self._customized = ma.user_customized_types()
        if self._built:
            self._refresh_defaults()
            return
        self._built = True

        index = ma.disambiguate_suffixes(ma.load_suffix_index())
        for mime in self._customized:
            index.setdefault(mime, [])  # e.g. x-scheme-handler/* have no suffix
        entries = sorted(index.items(), key=lambda kv: (kv[1][0] if kv[1] else kv[0]))

        token = object()
        self._build_token = token
        BATCH = 60

        def build(start=0):
            if self._build_token is not token:
                return False
            for mime, suffixes in entries[start:start + BATCH]:
                try:
                    self.list.append(_TypeRow(mime, suffixes))
                except Exception as e:  # noqa: BLE001 - one odd type must not blank the page
                    print(f"desktop-entry-editor: skipping file type {mime!r}: {e}")
            if start + BATCH < len(entries):
                GLib.idle_add(build, start + BATCH)
            else:
                self._update_empty()
            return False

        build()

    def _rows(self):
        i = 0
        while (row := self.list.get_row_at_index(i)) is not None:
            yield row
            i += 1

    def _refresh_defaults(self):
        rows = list(self._rows())

        def step(start=0):
            for row in rows[start:start + 100]:
                row.update_default()
            if start + 100 < len(rows):
                GLib.idle_add(step, start + 100)
            else:
                self.list.invalidate_filter()
                self._update_empty()
            return False

        step()

    # ------------------------------------------------------------------
    # Search / filter / sort
    # ------------------------------------------------------------------
    def _on_search_changed(self, entry):
        self._query = ma.normalize_suffix(entry.get_text())
        self._apply()

    def _on_only_changed(self, btn):
        self._only_changed = btn.get_active()
        self._customized = ma.user_customized_types()
        self._apply()

    def _apply(self):
        self.list.invalidate_filter()
        self.list.invalidate_sort()
        self._update_empty()

    def _visible(self, row) -> bool:
        if self._only_changed and row.mime not in self._customized:
            return False
        return row.matches(self._query)

    def _filter(self, row) -> bool:
        return self._visible(row)

    def _sort(self, a, b) -> int:
        ka = (a.rank(self._query), a.sort_key)
        kb = (b.rank(self._query), b.sort_key)
        return (ka > kb) - (ka < kb)

    def _update_empty(self):
        any_visible = any(self._visible(r) for r in self._rows())
        self.stack.set_visible_child(self._scroller if any_visible else self.empty)

    # ------------------------------------------------------------------
    # Changing an association
    # ------------------------------------------------------------------
    def _on_row_activated(self, _list, row):
        parent = self.get_root()

        def changed(message):
            self._on_toast(message)
            row.update_default()
            self._customized = ma.user_customized_types()

        def open_it():
            _AppChooserDialog(parent, row.mime, row.suffixes, changed).present()
            return False

        # Same pattern as the entries list: let the click finish first.
        GLib.idle_add(open_it)
