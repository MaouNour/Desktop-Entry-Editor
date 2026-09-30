"""
default_apps.py

The "Default Apps" page: one row per well-known role (Web Browser, Mail,
PDF viewer, ...) showing the current default application, with a drop-down
to change it and a button to fall back to the system default.

All the actual work is in mimeapps.py; this file is only the widgets.
"""
from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, GLib

from . import mimeapps as ma

# Which categories go into which group, in display order.
_GROUPS = (
    ("Internet", ("browser", "mail", "calendar", "contacts", "maps")),
    ("Files and Documents", ("files", "text", "pdf", "ebook", "archive", "torrent")),
    ("Media", ("image", "music", "video")),
)

_PLACEHOLDER_NOT_SET = "Not set"
_PLACEHOLDER_MIXED = "Mixed — pick one to use for all"


class _CategoryRow(Adw.ComboRow):
    def __init__(self, cat: ma.DefaultAppCategory, on_toast):
        super().__init__(title=cat.title)
        self.cat = cat
        self._on_toast = on_toast
        self._apps: list = []
        self._offset = 0
        self._updating = False

        self.icon = Gtk.Image(icon_name=cat.icon)
        self.add_prefix(self.icon)

        self.reset_btn = Gtk.Button(
            icon_name="edit-undo-symbolic", valign=Gtk.Align.CENTER,
            tooltip_text="Reset to the system default")
        self.reset_btn.add_css_class("flat")
        self.reset_btn.connect("clicked", self._on_reset)
        self.add_suffix(self.reset_btn)

        self.connect("notify::selected", self._on_selected)
        self.reload()

    # ------------------------------------------------------------------
    def reload(self):
        """Re-read everything from the system and rebuild the drop-down."""
        cat = self.cat
        primary, mixed = ma.category_state(cat)
        apps = ma.category_candidates(cat)

        labels: list[str] = []
        offset = 0
        if primary is None:
            labels.append(_PLACEHOLDER_NOT_SET)
            offset = 1
        elif mixed:
            labels.append(_PLACEHOLDER_MIXED)
            offset = 1
        labels.extend(ma.app_name(a) for a in apps)

        selected = 0
        if primary is not None and not mixed:
            ids = [ma.app_id(a) for a in apps]
            if ma.app_id(primary) in ids:
                selected = ids.index(ma.app_id(primary)) + offset

        self._updating = True
        try:
            self._apps = apps
            self._offset = offset
            self.set_model(Gtk.StringList.new(labels))
            self.set_selected(selected)
        finally:
            self._updating = False

        # Icon of whatever is currently the default.
        gicon = primary.get_icon() if primary is not None else None
        if gicon is not None and not mixed:
            self.icon.set_from_gicon(gicon)
        else:
            self.icon.set_from_icon_name(cat.icon)

        n = len(cat.mime_types)
        if mixed:
            self.set_subtitle("Related file types use different apps")
        elif not apps and primary is None:
            self.set_subtitle("No installed app can handle this")
        else:
            self.set_subtitle(f"Applies to {n} type{'s' if n != 1 else ''}" if n > 1 else cat.mime_types[0])
        self.set_tooltip_text("\n".join(cat.mime_types))

        customized = ma.user_customized_types()
        self.reset_btn.set_sensitive(any(m in customized for m in cat.mime_types))

    # ------------------------------------------------------------------
    def _on_selected(self, *_a):
        if self._updating:
            return
        idx = self.get_selected() - self._offset
        if idx < 0 or idx >= len(self._apps):
            return  # placeholder item chosen: nothing to apply
        app = self._apps[idx]
        errors = ma.set_default(app, self.cat.mime_types)
        if errors:
            self._on_toast(f"Could not set {self.cat.title}: {errors[0]}")
        else:
            self._on_toast(f"{self.cat.title}: {ma.app_name(app)}")
        # Rebuild after the signal handler returns (never mutate the
        # model from inside its own notify::selected emission).
        GLib.idle_add(self._reload_idle)

    def _reload_idle(self):
        self.reload()
        return False

    def _on_reset(self, *_a):
        errors = ma.reset_defaults(self.cat.mime_types)
        if errors:
            self._on_toast(f"Could not reset {self.cat.title}: {errors[0]}")
        else:
            self._on_toast(f"{self.cat.title}: back to system default")
        self.reload()


class DefaultAppsPage(Adw.Bin):
    """Scrollable page of default-application rows."""

    def __init__(self, on_toast=None):
        super().__init__()
        self._on_toast = on_toast or (lambda _msg: None)
        self._rows: list[_CategoryRow] = []

        page = Adw.PreferencesPage()
        first = True
        for title, keys in _GROUPS:
            group = Adw.PreferencesGroup(title=title)
            if first:
                group.set_description(
                    "Choices are saved to ~/.config/mimeapps.list and take "
                    "effect straight away — the same place GNOME Settings uses.")
                first = False
            for key in keys:
                cat = ma.category_by_key(key)
                if cat is None:
                    continue
                row = _CategoryRow(cat, self._on_toast)
                self._rows.append(row)
                group.add(row)
            page.add(group)
        self.set_child(page)

    def refresh(self):
        """Pick up changes made elsewhere (GNOME Settings, xdg-mime...)."""
        for row in self._rows:
            row.reload()
