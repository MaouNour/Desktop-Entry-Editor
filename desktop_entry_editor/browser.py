import os
import threading
import time

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, Gio, GLib, GObject

from .scanner import scan_all, category_counts, user_applications_dir, load_cached_infos, DesktopFileInfo

CAT_ALL = "__all__"
CAT_UNCATEGORIZED = "__uncategorized__"
CAT_HIDDEN = "__hidden__"

SOURCE_ICONS = {
    "User": "avatar-default-symbolic",
    "System": "computer-symbolic",
    "Flatpak": "package-x-generic-symbolic",
    "Snap": "package-x-generic-symbolic",
}


def _set_preview_icon(image: Gtk.Image, value: str):
    if not value:
        image.set_from_icon_name("application-x-executable-symbolic")
        return
    if os.path.isabs(value) or value.startswith("~") or "/" in value:
        path = os.path.expanduser(value)
        if os.path.exists(path):
            image.set_from_file(path)
        else:
            image.set_from_icon_name("application-x-executable-symbolic")
    else:
        image.set_from_icon_name(value)


class _EntryRow(Adw.ActionRow):
    def __init__(self, info: DesktopFileInfo):
        super().__init__()
        self.info = info
        self.set_activatable(True)

        icon = Gtk.Image(pixel_size=32)
        _set_preview_icon(icon, info.icon)
        self.add_prefix(icon)

        title = GLib.markup_escape_text(info.name or info.desktop_id)
        if info.error:
            self.set_title(title)
            self.set_subtitle(GLib.markup_escape_text(f"Could not parse: {info.error}"))
            self.add_css_class("error")
        else:
            self.set_title(title)
            subtitle = info.comment or info.path
            self.set_subtitle(GLib.markup_escape_text(subtitle))

        suffix_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6, valign=Gtk.Align.CENTER)

        if info.hidden or info.nodisplay:
            dim = Gtk.Image(icon_name="view-conceal-symbolic")
            dim.set_tooltip_text("Hidden / NoDisplay — not shown in menus")
            dim.add_css_class("dim-label")
            suffix_box.append(dim)

        if not info.writable:
            lock = Gtk.Image(icon_name="changes-prevent-symbolic")
            lock.set_tooltip_text("Read-only here — saving will offer to save a copy to your user applications folder")
            lock.add_css_class("dim-label")
            suffix_box.append(lock)

        source_icon = Gtk.Image(icon_name=SOURCE_ICONS.get(info.source, "folder-symbolic"), pixel_size=14)
        source_icon.add_css_class("dim-label")
        suffix_box.append(source_icon)

        badge = Gtk.Label(label=info.source)
        badge.add_css_class("caption")
        badge.add_css_class("dim-label")
        suffix_box.append(badge)

        self.add_suffix(suffix_box)
        self.set_activatable_widget(self)


class BrowserWindow(Adw.ApplicationWindow):
    """Lets the user browse every .desktop entry found on the system,
    grouped by category, search across them, and open any one (or a
    brand new blank one) in the full editor window."""

    def __init__(self, app):
        super().__init__(application=app)
        self.set_title("Desktop Entries")
        self.set_default_size(920, 640)
        self._app = app
        self._infos: list[DesktopFileInfo] = []
        self._current_category = CAT_ALL
        self._search_text = ""
        self._entry_list_build_token = None
        self._last_activated_path = None
        self._last_activated_at = 0.0

        self.toast_overlay = Adw.ToastOverlay()
        self._build_ui()
        self.set_content(self.toast_overlay)

        # Paint instantly from whatever was cached last run, then refresh
        # for real in the background — avoids staring at an empty list
        # every time the app opens.
        cached = load_cached_infos()
        if cached:
            self._infos = cached
            self._rebuild_sidebar()
            self._rebuild_entry_list()
            n = len(cached)
            self.window_title.set_subtitle(f"{n} entr{'y' if n == 1 else 'ies'} (refreshing…)")

        self.refresh()

    # ------------------------------------------------------------------
    def _build_ui(self):
        toolbar_view = Adw.ToolbarView()

        header = Adw.HeaderBar()
        self.window_title = Adw.WindowTitle(title="Desktop Entries", subtitle="Loading…")
        header.set_title_widget(self.window_title)

        refresh_btn = Gtk.Button(icon_name="view-refresh-symbolic", tooltip_text="Rescan (Ctrl+R)")
        refresh_btn.connect("clicked", lambda *_: self.refresh())
        header.pack_start(refresh_btn)

        search_btn = Gtk.ToggleButton(icon_name="edit-find-symbolic", tooltip_text="Search (Ctrl+F)")
        header.pack_start(search_btn)

        new_btn = Gtk.Button(icon_name="document-new-symbolic", tooltip_text="New Desktop Entry (Ctrl+N)")
        new_btn.add_css_class("suggested-action")
        new_btn.connect("clicked", lambda *_: self._app.open_editor_for_path(None))
        header.pack_end(new_btn)

        open_btn = Gtk.Button(icon_name="document-open-symbolic", tooltip_text="Open File… (Ctrl+O)")
        open_btn.connect("clicked", lambda *_: self._on_open_file())
        header.pack_end(open_btn)

        toolbar_view.add_top_bar(header)

        search_bar = Gtk.SearchBar()
        self.search_entry = Gtk.SearchEntry(placeholder_text="Search name, comment, exec, path…")
        search_bar.set_child(self.search_entry)
        search_bar.connect_entry(self.search_entry)
        self.search_entry.connect("search-changed", self._on_search_changed)
        search_bar.set_key_capture_widget(self)
        search_btn.bind_property("active", search_bar, "search-mode-enabled",
                                  GObject.BindingFlags.BIDIRECTIONAL)
        toolbar_view.add_top_bar(search_bar)

        split = Adw.NavigationSplitView()
        split.set_min_sidebar_width(200)
        split.set_max_sidebar_width(280)

        # -- Sidebar: categories -----------------------------------------
        self.category_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        self.category_list.add_css_class("navigation-sidebar")
        self.category_list.connect("row-selected", self._on_category_selected)
        sidebar_scroller = Gtk.ScrolledWindow(child=self.category_list, vexpand=True)
        sidebar_page = Adw.NavigationPage(title="Categories", child=sidebar_scroller)
        split.set_sidebar(sidebar_page)

        # -- Content: entry list ------------------------------------------
        self.entry_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.entry_list.add_css_class("boxed-list")
        self.entry_list.set_filter_func(self._filter_row)
        self.entry_list.connect("row-activated", self._on_row_activated)
        self.entry_list.set_margin_top(12)
        self.entry_list.set_margin_bottom(12)
        self.entry_list.set_margin_start(12)
        self.entry_list.set_margin_end(12)

        content_scroller = Gtk.ScrolledWindow(child=self.entry_list, vexpand=True)

        self.empty_status = Adw.StatusPage(
            title="No Entries Found",
            description="Try a different category or search term.",
            icon_name="edit-find-symbolic",
        )
        self.empty_status.set_visible(False)

        self.content_stack = Gtk.Stack()
        self.content_stack.add_child(content_scroller)
        self.content_stack.add_child(self.empty_status)
        self.content_stack.set_visible_child(content_scroller)
        self._content_scroller = content_scroller

        content_page = Adw.NavigationPage(title="Entries", child=self.content_stack)
        split.set_content(content_page)

        toolbar_view.set_content(split)
        self.toast_overlay.set_child(toolbar_view)

        # shortcuts
        self._install_action("win.rescan", lambda *_: self.refresh(), ["<primary>r"])
        self._install_action("win.new-entry", lambda *_: self._app.open_editor_for_path(None), ["<primary>n"])
        self._install_action("win.find", lambda *_: search_btn.set_active(True), ["<primary>f"])

    def _install_action(self, name, callback, accels):
        action_name = name.split(".", 1)[1]
        action = Gio.SimpleAction.new(action_name, None)
        action.connect("activate", lambda a, p: callback())
        self.add_action(action)
        self.get_application().set_accels_for_action(name, accels)

    # ------------------------------------------------------------------
    # Scanning
    # ------------------------------------------------------------------
    def refresh(self):
        if not self._infos:
            self.window_title.set_subtitle("Scanning…")

        def worker():
            try:
                infos = scan_all()
            except Exception as e:  # noqa: BLE001 - a scan failure must never crash the app
                print(f"desktop-entry-editor: scan failed: {e}")
                infos = None
            GLib.idle_add(self._on_scan_done, infos)

        threading.Thread(target=worker, daemon=True).start()

    def _on_scan_done(self, infos):
        try:
            if infos is not None:
                self._infos = infos
                self._rebuild_sidebar()
                self._rebuild_entry_list()
            n = len(self._infos)
            self.window_title.set_subtitle(f"{n} entr{'y' if n == 1 else 'ies'} found")
        except Exception as e:  # noqa: BLE001 - never let a rendering bug kill the app
            print(f"desktop-entry-editor: failed to display scan results: {e}")
            self.window_title.set_subtitle("Error loading entries")
        return False  # GLib.idle_add: don't repeat

    # ------------------------------------------------------------------
    # Sidebar
    # ------------------------------------------------------------------
    def _rebuild_sidebar(self):
        while (row := self.category_list.get_row_at_index(0)) is not None:
            self.category_list.remove(row)

        def add_row(key, label, count, icon_name):
            row = Adw.ActionRow(title=label, subtitle=f"{count}" if count is not None else "")
            if icon_name:
                row.add_prefix(Gtk.Image(icon_name=icon_name))
            row.category_key = key
            self.category_list.append(row)
            return row

        first_row = add_row(CAT_ALL, "All Entries", len(self._infos), "view-grid-symbolic")

        counts = category_counts(self._infos)
        for cat, n in counts.items():
            add_row(cat, cat, n, "folder-symbolic")

        uncategorized_n = sum(
            1 for i in self._infos
            if not i.error and not set(i.categories) & set(counts.keys())
        )
        if uncategorized_n:
            add_row(CAT_UNCATEGORIZED, "Uncategorized", uncategorized_n, "folder-symbolic")

        hidden_n = sum(1 for i in self._infos if i.hidden or i.nodisplay)
        if hidden_n:
            add_row(CAT_HIDDEN, "Hidden / NoDisplay", hidden_n, "view-conceal-symbolic")

        self.category_list.select_row(first_row)

    def _on_category_selected(self, _list, row):
        self._current_category = row.category_key if row else CAT_ALL
        self._rebuild_entry_list()

    # ------------------------------------------------------------------
    # Content list
    # ------------------------------------------------------------------
    def _rebuild_entry_list(self):
        while (row := self.entry_list.get_row_at_index(0)) is not None:
            self.entry_list.remove(row)

        # Building one Adw.ActionRow (with an icon lookup/load each) per
        # entry synchronously blocks the GTK main loop until every row is
        # built — with a few hundred installed entries (easy to reach
        # once Flatpak/Snap exports are included) that's a visible stall
        # right when the window is supposed to appear. Building in small
        # batches between main-loop iterations keeps the UI responsive
        # and paints progressively instead of freezing then popping in.
        infos = list(self._infos)
        BATCH = 40

        # Guards against a stale batch runner still adding rows after a
        # newer refresh() (or category rescan) has replaced self._infos.
        token = object()
        self._entry_list_build_token = token

        def build_batch(start=0):
            if self._entry_list_build_token is not token:
                return False  # a newer rebuild superseded this one
            end = min(start + BATCH, len(infos))
            for info in infos[start:end]:
                try:
                    self.entry_list.append(_EntryRow(info))
                except Exception as e:  # noqa: BLE001 - one bad entry must never blank the list
                    print(f"desktop-entry-editor: skipping unrenderable entry {info.path!r}: {e}")
            if end < len(infos):
                GLib.idle_add(build_batch, end)
            else:
                self.entry_list.invalidate_filter()
                self._update_empty_state()
            return False

        build_batch()

    def _on_search_changed(self, entry):
        self._search_text = entry.get_text().strip().lower()
        self.entry_list.invalidate_filter()
        self._update_empty_state()

    def _matches_category(self, info: DesktopFileInfo) -> bool:
        cat = self._current_category
        if cat == CAT_ALL:
            return True
        if cat == CAT_HIDDEN:
            return info.hidden or info.nodisplay
        if cat == CAT_UNCATEGORIZED:
            known = set(category_counts(self._infos).keys())
            return not info.error and not (set(info.categories) & known)
        return cat in info.categories

    def _matches_search(self, info: DesktopFileInfo) -> bool:
        if not self._search_text:
            return True
        haystack = " ".join([
            info.name or "", info.generic_name or "", info.comment or "",
            info.exec_cmd or "", info.path, info.desktop_id,
        ]).lower()
        return self._search_text in haystack

    def _filter_row(self, row) -> bool:
        info = row.info
        return self._matches_category(info) and self._matches_search(info)

    def _update_empty_state(self):
        any_visible = any(
            self._matches_category(row.info) and self._matches_search(row.info)
            for row in self._iter_entry_rows()
        )
        self.content_stack.set_visible_child(
            self._content_scroller if any_visible else self.empty_status
        )

    def _iter_entry_rows(self):
        i = 0
        while (row := self.entry_list.get_row_at_index(i)) is not None:
            yield row
            i += 1

    # Minimum gap between two activations of the *same* row that we'll
    # actually act on. A real double-click is ~0-400ms apart, so this is
    # generous for legitimate input -- but it's a hard backstop against
    # any runaway feedback loop between this handler and window
    # presentation (whatever triggers it), since a suppressed activation
    # does no work at all: no open_editor_for_path call, no present(),
    # nothing that could feed the loop further.
    _ACTIVATION_DEBOUNCE_SECONDS = 0.4

    def _on_row_activated(self, _list, row):
        from .debug_log import log
        now = time.monotonic()
        path = row.info.path
        if (path == self._last_activated_path
                and now - self._last_activated_at < self._ACTIVATION_DEBOUNCE_SECONDS):
            log(f"row-activated: {row.info.desktop_id!r} suppressed (debounced)")
            return
        self._last_activated_path = path
        self._last_activated_at = now

        log(f"row-activated: {row.info.desktop_id!r} path={row.info.path!r}")
        self._app.open_editor_for_path(row.info.path)
        log(f"row-activated: returned from open_editor_for_path for {row.info.desktop_id!r}")

    def _on_open_file(self):
        dialog = Gtk.FileDialog(title="Open Desktop Entry")
        filt = Gtk.FileFilter()
        filt.set_name("Desktop Entry files")
        filt.add_pattern("*.desktop")
        filt.add_pattern("*.directory")
        store = Gio.ListStore.new(Gtk.FileFilter)
        store.append(filt)
        all_filt = Gtk.FileFilter()
        all_filt.set_name("All files")
        all_filt.add_pattern("*")
        store.append(all_filt)
        dialog.set_filters(store)
        if os.path.isdir(user_applications_dir()):
            dialog.set_initial_folder(Gio.File.new_for_path(user_applications_dir()))

        def on_done(dlg, result):
            try:
                gfile = dlg.open_finish(result)
            except GLib.Error:
                return
            if gfile:
                self._app.open_editor_for_path(gfile.get_path())

        dialog.open(self, None, on_done)

    def toast(self, message: str):
        self.toast_overlay.add_toast(Adw.Toast(title=message, timeout=3))
