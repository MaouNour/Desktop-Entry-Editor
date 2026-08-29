import os
from collections import OrderedDict

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, Gio, GLib

from .desktop_entry import (
    DesktopEntry, DesktopEntryError, MAIN_GROUP,
    MAIN_CATEGORIES, ADDITIONAL_CATEGORIES, DESKTOP_ENVIRONMENTS,
    TYPE_CHOICES, LOCALIZABLE_KEYS,
)
from .icon_row import IconEntryRow
from .localization_dialog import LocalizationDialog

EXEC_FIELD_CODE_HELP = (
    "%f  a single file path\n"
    "%F  a list of file paths\n"
    "%u  a single URL\n"
    "%U  a list of URLs\n"
    "%i  --icon <Icon value>, if an icon is set\n"
    "%c  the translated application Name\n"
    "%k  the location of this .desktop file\n"
    "%%  a literal percent sign"
)


def _globe_button(tooltip="Edit translations"):
    b = Gtk.Button(icon_name="preferences-desktop-locale-symbolic", valign=Gtk.Align.CENTER)
    b.add_css_class("flat")
    b.set_tooltip_text(tooltip)
    return b


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, app, path: str | None = None):
        super().__init__(application=app)
        self.set_default_size(880, 720)
        self.entry: DesktopEntry = DesktopEntry.new_application()
        self._dirty = False
        self._loading = False
        self._path: str | None = None

        self.toast_overlay = Adw.ToastOverlay()
        self._build_ui()
        self.set_content(self.toast_overlay)

        self.connect("close-request", self._on_close_request)

        if path:
            self.load_path(path)
        else:
            self._refresh_all()
            self._update_title()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _build_ui(self):
        toolbar_view = Adw.ToolbarView()

        header = Adw.HeaderBar()
        # STRICT keeps the title widget mathematically centered in the
        # header bar even though the start side (New/Open) and end side
        # (Save/Save As/Run) have a different number of buttons. With the
        # default LOOSE policy the title just sits centered *between* the
        # two button groups, which visibly drifts off-center whenever
        # those groups are different widths.
        header.set_centering_policy(Adw.CenteringPolicy.STRICT)
        self.window_title = Adw.WindowTitle(title="Desktop Entry Editor")
        header.set_title_widget(self.window_title)

        new_btn = Gtk.Button(icon_name="document-new-symbolic", tooltip_text="New (Ctrl+N)")
        new_btn.connect("clicked", lambda *_: self._on_new())
        header.pack_start(new_btn)

        open_btn = Gtk.Button(icon_name="document-open-symbolic", tooltip_text="Open (Ctrl+O)")
        open_btn.connect("clicked", lambda *_: self._on_open())
        header.pack_start(open_btn)

        save_btn = Gtk.Button(icon_name="document-save-symbolic", tooltip_text="Save (Ctrl+S)")
        save_btn.add_css_class("suggested-action")
        save_btn.connect("clicked", lambda *_: self._on_save())
        header.pack_end(save_btn)
        self.save_button = save_btn

        save_as_btn = Gtk.Button(icon_name="document-save-as-symbolic", tooltip_text="Save As (Ctrl+Shift+S)")
        save_as_btn.connect("clicked", lambda *_: self._on_save_as())
        header.pack_end(save_as_btn)

        run_btn = Gtk.Button(icon_name="media-playback-start-symbolic", tooltip_text="Test run Exec= command")
        run_btn.connect("clicked", lambda *_: self._on_test_run())
        header.pack_end(run_btn)

        toolbar_view.add_top_bar(header)

        self.stack = Adw.ViewStack()
        self.switcher_bar = Adw.ViewSwitcherBar()
        self.switcher_bar.set_stack(self.stack)
        # Always keep the tab bar visible and pinned to the bottom instead
        # of letting it swap places with the header bar's title. That
        # swap (Adw.ViewSwitcherTitle's normal adaptive behaviour) is what
        # caused the "header disappears / tab bar jumps to the top" glitch
        # when maximizing or fullscreening: past a certain width libadwaita
        # replaces the header title with an inline copy of the switcher,
        # which briefly overlaps/relayouts badly with the bottom bar
        # during the resize. Pinning it here keeps the layout identical
        # (and predictable) in every window state.
        self.switcher_bar.set_reveal(True)

        toolbar_view.set_content(self.stack)
        toolbar_view.add_bottom_bar(self.switcher_bar)
        self.toast_overlay.set_child(toolbar_view)

        self._build_basic_page()
        self._build_exec_page()
        self._build_categories_page()
        self._build_keywords_page()
        self._build_visibility_page()
        self._build_actions_page()
        self._build_source_page()

        # keyboard shortcuts
        app = self.get_application()
        self._install_action("win.new", lambda *_: self._on_new(), ["<primary>n"])
        self._install_action("win.open", lambda *_: self._on_open(), ["<primary>o"])
        self._install_action("win.save", lambda *_: self._on_save(), ["<primary>s"])
        self._install_action("win.save-as", lambda *_: self._on_save_as(), ["<primary><shift>s"])

    def _install_action(self, name, callback, accels):
        action_name = name.split(".", 1)[1]
        action = Gio.SimpleAction.new(action_name, None)
        action.connect("activate", lambda a, p: callback())
        self.add_action(action)
        self.get_application().set_accels_for_action(name, accels)

    def _add_page(self, widget, name, title, icon_name):
        page = self.stack.add_titled(widget, name, title)
        page.set_icon_name(icon_name)
        return page

    def _scrolled_prefs_page(self):
        page = Adw.PreferencesPage()
        return page

    # -- Basic ------------------------------------------------------------
    def _build_basic_page(self):
        page = self._scrolled_prefs_page()

        type_group = Adw.PreferencesGroup(title="Entry Type")
        self.type_row = Adw.ComboRow(title="Type", subtitle="What this entry launches")
        self.type_row.set_model(Gtk.StringList.new(TYPE_CHOICES))
        self.type_row.connect("notify::selected", self._on_type_changed)
        type_group.add(self.type_row)
        page.add(type_group)

        ident_group = Adw.PreferencesGroup(title="Identity")

        self.name_row = Adw.EntryRow(title="Name")
        self.name_row.set_tooltip_text("The name shown to the user, e.g. in application menus")
        gb = _globe_button()
        gb.connect("clicked", lambda *_: self._open_localization("Name", self.name_row))
        self.name_row.add_suffix(gb)
        self.name_row.connect("changed", lambda *_: self._commit_entry_text("Name", self.name_row))
        ident_group.add(self.name_row)

        self.generic_name_row = Adw.EntryRow(title="Generic Name")
        self.generic_name_row.set_tooltip_text('A generic descriptor, e.g. "Web Browser"')
        gb2 = _globe_button()
        gb2.connect("clicked", lambda *_: self._open_localization("GenericName", self.generic_name_row))
        self.generic_name_row.add_suffix(gb2)
        self.generic_name_row.connect("changed", lambda *_: self._commit_entry_text("GenericName", self.generic_name_row))
        ident_group.add(self.generic_name_row)

        self.comment_row = Adw.EntryRow(title="Comment")
        self.comment_row.set_tooltip_text("Tooltip / description text")
        gb3 = _globe_button()
        gb3.connect("clicked", lambda *_: self._open_localization("Comment", self.comment_row))
        self.comment_row.add_suffix(gb3)
        self.comment_row.connect("changed", lambda *_: self._commit_entry_text("Comment", self.comment_row))
        ident_group.add(self.comment_row)

        self.icon_row = IconEntryRow(title="Icon")
        self.icon_row.set_tooltip_text("Icon theme name (e.g. 'firefox') or absolute path to an image")
        self.icon_row.connect("value-changed", lambda _r, v: self._commit_raw("Icon", v))
        ident_group.add(self.icon_row)

        self.version_row = Adw.EntryRow(title="Version")
        self.version_row.set_tooltip_text("Desktop Entry Specification version this file conforms to, e.g. 1.5")
        self.version_row.connect("changed", lambda *_: self._commit_entry_text("Version", self.version_row))
        ident_group.add(self.version_row)

        page.add(ident_group)

        vis_group = Adw.PreferencesGroup(title="Visibility Flags")
        self.no_display_row = Adw.SwitchRow(
            title="No Display",
            subtitle="Hide from menus (this entry is only used indirectly, e.g. by MIME associations)",
        )
        self.no_display_row.connect("notify::active", lambda *_: self._commit_bool("NoDisplay", self.no_display_row))
        vis_group.add(self.no_display_row)

        self.hidden_row = Adw.SwitchRow(
            title="Hidden",
            subtitle="Marks this entry as deleted / should be completely ignored",
        )
        self.hidden_row.connect("notify::active", lambda *_: self._commit_bool("Hidden", self.hidden_row))
        vis_group.add(self.hidden_row)

        page.add(vis_group)

        self._add_page(page, "basic", "Basic", "emblem-default-symbolic")

    # -- Execution ----------------------------------------------------------
    def _build_exec_page(self):
        page = self._scrolled_prefs_page()

        run_group = Adw.PreferencesGroup(
            title="Launch Command",
            description="Only used when Type is Application",
        )
        self.exec_row = Adw.EntryRow(title="Exec")
        help_btn = Gtk.Button(icon_name="help-about-symbolic", valign=Gtk.Align.CENTER)
        help_btn.add_css_class("flat")
        help_btn.set_tooltip_text(EXEC_FIELD_CODE_HELP)
        self.exec_row.add_suffix(help_btn)
        self.exec_row.connect("changed", lambda *_: self._commit_entry_text("Exec", self.exec_row))
        run_group.add(self.exec_row)

        self.tryexec_row = Adw.EntryRow(title="TryExec")
        self.tryexec_row.set_tooltip_text(
            "Optional executable name to check for existence before showing this entry"
        )
        self.tryexec_row.connect("changed", lambda *_: self._commit_entry_text("TryExec", self.tryexec_row))
        run_group.add(self.tryexec_row)

        self.path_row = Adw.EntryRow(title="Path")
        self.path_row.set_tooltip_text("Working directory the program should run in")
        self.path_row.connect("changed", lambda *_: self._commit_entry_text("Path", self.path_row))
        run_group.add(self.path_row)

        self.url_row = Adw.EntryRow(title="URL")
        self.url_row.set_tooltip_text("Target URL, only used when Type is Link")
        self.url_row.connect("changed", lambda *_: self._commit_entry_text("URL", self.url_row))
        run_group.add(self.url_row)

        page.add(run_group)
        self.run_group = run_group

        behaviour_group = Adw.PreferencesGroup(title="Behaviour")

        self.terminal_row = Adw.SwitchRow(title="Run in Terminal")
        self.terminal_row.connect("notify::active", lambda *_: self._commit_bool("Terminal", self.terminal_row))
        behaviour_group.add(self.terminal_row)

        self.startup_notify_row = Adw.SwitchRow(
            title="Startup Notify",
            subtitle="Show a loading indicator while the app starts",
        )
        self.startup_notify_row.connect("notify::active", lambda *_: self._commit_bool("StartupNotify", self.startup_notify_row))
        behaviour_group.add(self.startup_notify_row)

        self.dbus_activatable_row = Adw.SwitchRow(
            title="D-Bus Activatable",
            subtitle="App can be activated via D-Bus using its Application ID",
        )
        self.dbus_activatable_row.connect("notify::active", lambda *_: self._commit_bool("DBusActivatable", self.dbus_activatable_row))
        behaviour_group.add(self.dbus_activatable_row)

        self.single_main_window_row = Adw.SwitchRow(
            title="Single Main Window",
            subtitle="Hint that activating again should focus the existing window",
        )
        self.single_main_window_row.connect("notify::active", lambda *_: self._commit_bool("SingleMainWindow", self.single_main_window_row))
        behaviour_group.add(self.single_main_window_row)

        self.prefers_gpu_row = Adw.SwitchRow(
            title="Prefers Non-Default GPU",
            subtitle="Hint to launch using a discrete/high-performance GPU",
        )
        self.prefers_gpu_row.connect("notify::active", lambda *_: self._commit_bool("PrefersNonDefaultGPU", self.prefers_gpu_row))
        behaviour_group.add(self.prefers_gpu_row)

        page.add(behaviour_group)

        wm_group = Adw.PreferencesGroup(
            title="Window Matching",
            description="Helps the desktop shell match running windows back to this launcher",
        )
        self.wmclass_row = Adw.EntryRow(title="StartupWMClass")
        self.wmclass_row.set_tooltip_text(
            "The WM_CLASS property of the application's main window "
            "(check with `xprop WM_CLASS` on X11)"
        )
        self.wmclass_row.connect("changed", lambda *_: self._commit_entry_text("StartupWMClass", self.wmclass_row))
        wm_group.add(self.wmclass_row)
        page.add(wm_group)

        self._add_page(page, "exec", "Execution", "utilities-terminal-symbolic")

    # -- Categories ----------------------------------------------------------
    def _build_categories_page(self):
        page = self._scrolled_prefs_page()

        main_group = Adw.PreferencesGroup(
            title="Main Categories",
            description="Every application entry should have at least one of these",
        )
        self._category_checks = {}
        main_flow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=3, row_spacing=4, column_spacing=12)
        for cat in MAIN_CATEGORIES:
            cb = Gtk.CheckButton(label=cat)
            cb.connect("toggled", self._on_category_toggled)
            self._category_checks[cat] = cb
            main_flow.append(cb)
        main_group.add(main_flow)
        page.add(main_group)

        add_group = Adw.PreferencesGroup(title="Additional Categories")
        add_expander = Adw.ExpanderRow(title="Show all additional categories", subtitle=f"{len(ADDITIONAL_CATEGORIES)} available")
        add_flow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=3, row_spacing=4, column_spacing=12,
                                margin_top=6, margin_bottom=6, margin_start=6, margin_end=6)
        for cat in ADDITIONAL_CATEGORIES:
            cb = Gtk.CheckButton(label=cat)
            cb.connect("toggled", self._on_category_toggled)
            self._category_checks[cat] = cb
            add_flow.append(cb)
        add_row = Gtk.ListBoxRow(selectable=False, activatable=False)
        add_row.set_child(add_flow)
        add_expander.add_row(add_row)
        add_group.add(add_expander)
        page.add(add_group)

        custom_group = Adw.PreferencesGroup(
            title="Custom / Unlisted Categories",
            description="Semicolon-separated; use this for categories not listed above",
        )
        self.custom_categories_row = Adw.EntryRow(title="Custom Categories")
        self.custom_categories_row.connect("changed", self._on_custom_categories_changed)
        custom_group.add(self.custom_categories_row)
        page.add(custom_group)

        self._add_page(page, "categories", "Categories", "view-grid-symbolic")

    def _on_category_toggled(self, *_a):
        if self._loading:
            return
        selected = [cat for cat, cb in self._category_checks.items() if cb.get_active()]
        custom = _parse_semicolon_text(self.custom_categories_row.get_text())
        self._loading = True
        self.entry.main.set_list("Categories", selected + custom)
        self._loading = False
        self._mark_dirty()

    def _on_custom_categories_changed(self, *_a):
        if self._loading:
            return
        self._on_category_toggled()

    # -- Keywords / MIME ------------------------------------------------------
    def _build_keywords_page(self):
        page = self._scrolled_prefs_page()

        kw_group = Adw.PreferencesGroup(
            title="Keywords",
            description="Extra search terms used by application launchers (semicolon-separated)",
        )
        self.keywords_row = Adw.EntryRow(title="Keywords")
        gb = _globe_button()
        gb.connect("clicked", lambda *_: self._open_localization("Keywords", self.keywords_row, is_list=True))
        self.keywords_row.add_suffix(gb)
        self.keywords_row.connect("changed", lambda *_: self._commit_list("Keywords", self.keywords_row))
        kw_group.add(self.keywords_row)
        page.add(kw_group)

        mime_group = Adw.PreferencesGroup(
            title="MIME Types",
            description="File types this application can open (semicolon-separated, e.g. text/plain;image/png)",
        )
        self.mimetype_row = Adw.EntryRow(title="MimeType")
        self.mimetype_row.connect("changed", lambda *_: self._commit_list("MimeType", self.mimetype_row))
        mime_group.add(self.mimetype_row)
        page.add(mime_group)

        implements_group = Adw.PreferencesGroup(
            title="Implements",
            description="Interfaces this application implements, mainly for D-Bus activation (semicolon-separated)",
        )
        self.implements_row = Adw.EntryRow(title="Implements")
        self.implements_row.connect("changed", lambda *_: self._commit_list("Implements", self.implements_row))
        implements_group.add(self.implements_row)
        page.add(implements_group)

        self._add_page(page, "keywords", "Keywords & MIME", "tag-symbolic")

    # -- Visibility (OnlyShowIn / NotShowIn) -----------------------------------
    def _build_visibility_page(self):
        page = self._scrolled_prefs_page()

        info_group = Adw.PreferencesGroup(
            title="Desktop Environment Filtering",
            description="Use at most one of these two: restrict to specific desktop "
                        "environments, or hide from specific ones.",
        )
        page.add(info_group)

        only_group = Adw.PreferencesGroup(title="Only Show In")
        self._only_show_checks = {}
        only_flow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=4, row_spacing=4, column_spacing=12)
        for de in DESKTOP_ENVIRONMENTS:
            cb = Gtk.CheckButton(label=de)
            cb.connect("toggled", lambda _cb, de=de: self._on_show_in_toggled("OnlyShowIn"))
            self._only_show_checks[de] = cb
            only_flow.append(cb)
        only_group.add(only_flow)
        page.add(only_group)

        not_group = Adw.PreferencesGroup(title="Not Show In")
        self._not_show_checks = {}
        not_flow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=4, row_spacing=4, column_spacing=12)
        for de in DESKTOP_ENVIRONMENTS:
            cb = Gtk.CheckButton(label=de)
            cb.connect("toggled", lambda _cb, de=de: self._on_show_in_toggled("NotShowIn"))
            self._not_show_checks[de] = cb
            not_flow.append(cb)
        not_group.add(not_flow)
        page.add(not_group)

        self._add_page(page, "visibility", "Visibility", "view-reveal-symbolic")

    def _on_show_in_toggled(self, key):
        if self._loading:
            return
        checks = self._only_show_checks if key == "OnlyShowIn" else self._not_show_checks
        selected = [de for de, cb in checks.items() if cb.get_active()]
        self.entry.main.set_list(key, selected)
        self._mark_dirty()

    # -- Actions ----------------------------------------------------------
    def _build_actions_page(self):
        page = self._scrolled_prefs_page()
        self.actions_group = Adw.PreferencesGroup(
            title="Custom Actions",
            description="Extra entries shown in the app's right-click menu in application launchers",
        )
        add_btn = Gtk.Button(label="Add Action")
        add_btn.add_css_class("flat")
        add_btn.connect("clicked", lambda *_: self._on_add_action())
        self.actions_group.set_header_suffix(add_btn)
        page.add(self.actions_group)
        self._add_page(page, "actions", "Actions", "list-add-symbolic")

    def _on_add_action(self):
        i = 1
        existing = set(self.entry.list_actions())
        while f"Action{i}" in existing:
            i += 1
        action_id = f"Action{i}"
        self.entry.add_action(action_id, name="New Action", exec_cmd="")
        self._mark_dirty()
        self._refresh_actions()

    def _refresh_actions(self):
        child = self.actions_group.get_first_child()
        # Adw.PreferencesGroup doesn't give a simple "clear"; rebuild rows list manually
        for row in list(getattr(self, "_action_rows", [])):
            self.actions_group.remove(row)
        self._action_rows = []

        for action_id in self.entry.list_actions():
            group = self.entry.get_action_group(action_id)
            expander = Adw.ExpanderRow(title=group.get("Name", default=action_id), subtitle=f"ID: {action_id}")

            id_row = Adw.EntryRow(title="Action ID")
            id_row.set_text(action_id)

            def on_id_changed(row, old_id=action_id, expander=expander):
                new_id = row.get_text().strip()
                if not new_id or new_id == old_id:
                    return
                try:
                    self.entry.rename_action(old_id, new_id)
                except DesktopEntryError as e:
                    self._toast(str(e))
                    return
                self._mark_dirty()
                self._refresh_actions()
            id_row.connect("apply", on_id_changed)
            expander.add_row(id_row)

            name_row = Adw.EntryRow(title="Name")
            name_row.set_text(group.get("Name"))

            def on_name_changed(row, group=group, expander=expander):
                expander.set_title(row.get_text() or "(unnamed)")
                if self._loading:
                    return
                group.set("Name", row.get_text())
                self._mark_dirty()
            name_row.connect("changed", on_name_changed)
            expander.add_row(name_row)

            icon_row = IconEntryRow(title="Icon")
            icon_row.set_value(group.get("Icon"))

            def on_icon_changed(_row, value, group=group):
                if self._loading:
                    return
                if value:
                    group.set("Icon", value)
                else:
                    group.delete("Icon")
                self._mark_dirty()
            icon_row.connect("value-changed", on_icon_changed)
            expander.add_row(icon_row)

            exec_row = Adw.EntryRow(title="Exec")
            exec_row.set_text(group.get("Exec"))

            def on_exec_changed(row, group=group):
                if self._loading:
                    return
                group.set("Exec", row.get_text())
                self._mark_dirty()
            exec_row.connect("changed", on_exec_changed)
            expander.add_row(exec_row)

            remove_btn = Gtk.Button(icon_name="user-trash-symbolic", valign=Gtk.Align.CENTER)
            remove_btn.add_css_class("flat")
            remove_btn.set_tooltip_text("Remove this action")

            def on_remove(_b, action_id=action_id):
                self.entry.remove_action(action_id)
                self._mark_dirty()
                self._refresh_actions()
            remove_btn.connect("clicked", on_remove)
            expander.add_suffix(remove_btn)

            self.actions_group.add(expander)
            self._action_rows.append(expander)

    # -- Raw source ----------------------------------------------------------
    def _build_source_page(self):
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8,
                        margin_top=12, margin_bottom=12, margin_start=12, margin_end=12)

        info = Gtk.Label(
            label="Raw file contents. Edit directly and click Apply to parse changes back "
                  "into the editor, or Revert to discard them.",
            wrap=True, xalign=0,
        )
        info.add_css_class("dim-label")
        page.append(info)

        scroller = Gtk.ScrolledWindow(vexpand=True)
        self.source_view = Gtk.TextView(monospace=True, top_margin=8, bottom_margin=8, left_margin=8, right_margin=8)
        self.source_view.get_buffer().connect("changed", lambda *_: self._update_source_buttons())
        scroller.set_child(self.source_view)
        scroller.add_css_class("card")
        page.append(scroller)

        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8, halign=Gtk.Align.END)
        self.source_revert_btn = Gtk.Button(label="Revert")
        self.source_revert_btn.connect("clicked", lambda *_: self._refresh_source())
        self.source_apply_btn = Gtk.Button(label="Apply")
        self.source_apply_btn.add_css_class("suggested-action")
        self.source_apply_btn.connect("clicked", lambda *_: self._apply_source())
        btn_box.append(self.source_revert_btn)
        btn_box.append(self.source_apply_btn)
        page.append(btn_box)

        self._add_page(page, "source", "Source", "text-x-generic-symbolic")

    def _refresh_source(self):
        self.source_view.get_buffer().set_text(self.entry.to_string())
        self._update_source_buttons()

    def _update_source_buttons(self):
        pass  # placeholder for future dirty-state styling on the source page

    def _apply_source(self):
        buf = self.source_view.get_buffer()
        text = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), True)
        try:
            new_entry = DesktopEntry.from_string(text)
        except Exception as e:  # noqa: BLE001 - surface any parse issue to the user
            self._toast(f"Could not parse: {e}")
            return
        new_entry.path = self.entry.path
        self.entry = new_entry
        self._mark_dirty()
        self._refresh_all()
        self._toast("Source applied")

    # ------------------------------------------------------------------
    # Loading values from self.entry into the widgets
    # ------------------------------------------------------------------
    def _refresh_all(self):
        self._loading = True
        try:
            m = self.entry.main
            type_val = m.get("Type", default="Application")
            try:
                idx = TYPE_CHOICES.index(type_val)
            except ValueError:
                idx = 0
            self.type_row.set_selected(idx)

            self.name_row.set_text(m.get("Name"))
            self.generic_name_row.set_text(m.get("GenericName"))
            self.comment_row.set_text(m.get("Comment"))
            self.icon_row.set_value(m.get("Icon"))
            self.version_row.set_text(m.get("Version"))
            self.no_display_row.set_active(m.get_bool("NoDisplay"))
            self.hidden_row.set_active(m.get_bool("Hidden"))

            self.exec_row.set_text(m.get("Exec"))
            self.tryexec_row.set_text(m.get("TryExec"))
            self.path_row.set_text(m.get("Path"))
            self.url_row.set_text(m.get("URL"))
            self.terminal_row.set_active(m.get_bool("Terminal"))
            self.startup_notify_row.set_active(m.get_bool("StartupNotify"))
            self.dbus_activatable_row.set_active(m.get_bool("DBusActivatable"))
            self.single_main_window_row.set_active(m.get_bool("SingleMainWindow"))
            self.prefers_gpu_row.set_active(m.get_bool("PrefersNonDefaultGPU"))
            self.wmclass_row.set_text(m.get("StartupWMClass"))

            categories = m.get_list("Categories")
            known = set(self._category_checks.keys())
            for cat, cb in self._category_checks.items():
                cb.set_active(cat in categories)
            custom = [c for c in categories if c not in known]
            self.custom_categories_row.set_text(_format_semicolon_text(custom))

            self.keywords_row.set_text(_format_semicolon_text(m.get_list("Keywords")))
            self.mimetype_row.set_text(_format_semicolon_text(m.get_list("MimeType")))
            self.implements_row.set_text(_format_semicolon_text(m.get_list("Implements")))

            only_show = set(m.get_list("OnlyShowIn"))
            not_show = set(m.get_list("NotShowIn"))
            for de, cb in self._only_show_checks.items():
                cb.set_active(de in only_show)
            for de, cb in self._not_show_checks.items():
                cb.set_active(de in not_show)

            self._refresh_actions()
            self._refresh_source()
            self._update_visible_pages()
        finally:
            self._loading = False

    def _update_visible_pages(self):
        type_val = TYPE_CHOICES[self.type_row.get_selected()]
        self.run_group.set_visible(type_val in ("Application", "Link"))
        self.exec_row.set_visible(type_val == "Application")
        self.tryexec_row.set_visible(type_val == "Application")
        self.url_row.set_visible(type_val == "Link")

    # ------------------------------------------------------------------
    # Writing widget values back into self.entry
    # ------------------------------------------------------------------
    def _commit_entry_text(self, key, row):
        if self._loading:
            return
        self.entry.main.set(key, row.get_text())
        self._mark_dirty()

    def _commit_raw(self, key, value):
        if self._loading:
            return
        if value:
            self.entry.main.set(key, value)
        else:
            self.entry.main.delete(key)
        self._mark_dirty()

    def _commit_bool(self, key, row):
        if self._loading:
            return
        self.entry.main.set_bool(key, row.get_active())
        self._mark_dirty()

    def _commit_list(self, key, row):
        if self._loading:
            return
        items = _parse_semicolon_text(row.get_text())
        self.entry.main.set_list(key, items)
        self._mark_dirty()

    def _on_type_changed(self, *_a):
        if not self._loading:
            self.entry.main.set("Type", TYPE_CHOICES[self.type_row.get_selected()])
            self._mark_dirty()
        self._update_visible_pages()

    # ------------------------------------------------------------------
    # Localization dialog plumbing
    # ------------------------------------------------------------------
    def _open_localization(self, key, row, is_list=False):
        values = self.entry.get_localized_map(key)
        dialog = LocalizationDialog(key, values, is_list=is_list)

        def on_closed(*_a):
            new_values = dialog.get_values()
            # remove any locale no longer present
            old_locales = set(values.keys())
            new_locales = set(new_values.keys())
            for locale in old_locales - new_locales:
                self.entry.remove_localized(key, locale)
            for locale, text in new_values.items():
                self.entry.set_localized(key, locale, text)
            self._mark_dirty()
            if key in ("Name", "GenericName", "Comment"):
                # keep the base-language row in sync
                self._loading = True
                row.set_text(self.entry.main.get(key))
                self._loading = False

        dialog.connect("closed", on_closed)
        dialog.present(self)

    # ------------------------------------------------------------------
    # File operations
    # ------------------------------------------------------------------
    def load_path(self, path: str):
        try:
            self.entry = DesktopEntry.from_file(path)
        except Exception as e:  # noqa: BLE001
            self._toast(f"Could not open {path}: {e}")
            return
        self._path = path
        self._dirty = False
        self._refresh_all()
        self._update_title()

    def _on_new(self):
        def do_new():
            self.entry = DesktopEntry.new_application()
            self._path = None
            self._dirty = False
            self._refresh_all()
            self._update_title()

        if self._dirty:
            self._confirm_discard(do_new)
        else:
            do_new()

    def _on_open(self):
        def do_open():
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

            def on_done(dlg, result):
                try:
                    gfile = dlg.open_finish(result)
                except GLib.Error:
                    return
                if gfile:
                    self.load_path(gfile.get_path())

            dialog.open(self, None, on_done)

        if self._dirty:
            self._confirm_discard(do_open)
        else:
            do_open()

    def _on_save(self):
        if self._path:
            self._save_to(self._path)
        else:
            self._on_save_as()

    def _on_save_as(self):
        dialog = Gtk.FileDialog(title="Save Desktop Entry")
        default_name = "application.desktop"
        m = self.entry.main
        if m.get("Name"):
            safe = "".join(c for c in m.get("Name") if c.isalnum() or c in " -_").strip()
            if safe:
                default_name = safe.replace(" ", "") + ".desktop"
        dialog.set_initial_name(default_name)
        if self._path:
            parent = os.path.dirname(self._path)
            if parent and os.path.isdir(parent):
                dialog.set_initial_folder(Gio.File.new_for_path(parent))

        def on_done(dlg, result):
            try:
                gfile = dlg.save_finish(result)
            except GLib.Error:
                return
            if gfile:
                self._save_to(gfile.get_path())

        dialog.save(self, None, on_done)

    def _save_to(self, path: str):
        try:
            self.entry.save(path)
        except Exception as e:  # noqa: BLE001
            self._toast(f"Could not save: {e}")
            return
        self._path = path
        self._dirty = False
        self._update_title()
        self._toast(f"Saved {os.path.basename(path)}")

    def _on_test_run(self):
        import shlex
        import subprocess
        exec_line = self.entry.main.get("Exec")
        if not exec_line:
            self._toast("No Exec command set")
            return
        cleaned = exec_line
        for code in ("%f", "%F", "%u", "%U", "%i", "%c", "%k"):
            cleaned = cleaned.replace(code, "")
        cleaned = cleaned.replace("%%", "%").strip()
        try:
            args = shlex.split(cleaned)
            subprocess.Popen(args)
            self._toast(f"Launched: {cleaned}")
        except Exception as e:  # noqa: BLE001
            self._toast(f"Failed to launch: {e}")

    # ------------------------------------------------------------------
    # Misc
    # ------------------------------------------------------------------
    def _mark_dirty(self):
        self._dirty = True
        self._update_title()

    def _update_title(self):
        name = self.entry.main.get("Name") or "Untitled"
        marker = "•  " if self._dirty else ""
        self.set_title(f"{marker}{name} — Desktop Entry Editor")
        self.window_title.set_title(f"{marker}Desktop Entry Editor")
        self.window_title.set_subtitle(self._path or name)

    def _toast(self, message: str):
        self.toast_overlay.add_toast(Adw.Toast(title=message, timeout=3))

    def _confirm_discard(self, on_confirm):
        dialog = Adw.AlertDialog(
            heading="Discard unsaved changes?",
            body="You have unsaved changes that will be lost.",
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("discard", "Discard")
        dialog.set_response_appearance("discard", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")

        def on_response(_d, response):
            if response == "discard":
                on_confirm()

        dialog.connect("response", on_response)
        dialog.present(self)

    def _on_close_request(self, *_a):
        if self._dirty:
            def discard_and_close():
                # Clear the dirty flag first: close() re-emits
                # "close-request", and without this the handler would
                # just show the confirmation dialog again forever.
                self._dirty = False
                self.close()
            self._confirm_discard(discard_and_close)
            return True
        return False


def _parse_semicolon_text(text: str) -> list[str]:
    return [p.strip() for p in text.split(";") if p.strip()]


def _format_semicolon_text(items: list[str]) -> str:
    return "; ".join(items)
