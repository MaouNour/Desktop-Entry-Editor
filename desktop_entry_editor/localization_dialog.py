"""A small dialog for editing the localized ([xx]) variants of a key,
e.g. Name, Name[fr], Name[de_DE], Comment[pt_BR], Keywords[es]..."""
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, GObject


class LocalizationDialog(Adw.Dialog):
    """Edit every locale variant of a single key.

    `values` is an OrderedDict of {locale_or_None: string_value}.
    Call `get_values()` after the dialog closes to retrieve the result.
    """

    def __init__(self, key_label: str, values, is_list: bool = False, **kwargs):
        super().__init__(**kwargs)
        self.set_title(f"Translations for “{key_label}”")
        self.set_content_width(480)
        self.set_content_height(420)
        self._is_list = is_list
        self._rows = {}  # locale -> (Adw.EntryRow, remove_button or None)

        toolbar_view = Adw.ToolbarView()
        header = Adw.HeaderBar()
        header.set_show_end_title_buttons(True)
        toolbar_view.add_top_bar(header)

        add_button = Gtk.Button(icon_name="list-add-symbolic")
        add_button.set_tooltip_text("Add a locale")
        add_button.connect("clicked", self._on_add_locale)
        header.pack_start(add_button)

        done_button = Gtk.Button(label="Done")
        done_button.add_css_class("suggested-action")
        done_button.connect("clicked", lambda *_: self.close())
        header.pack_end(done_button)

        scroller = Gtk.ScrolledWindow(vexpand=True)
        clamp = Adw.Clamp(margin_top=12, margin_bottom=12, margin_start=12, margin_end=12)
        self._group = Adw.PreferencesGroup()
        self._group.set_description(
            "The unlabeled entry is the default value used when no "
            "translation matches the user's locale."
        )
        clamp.set_child(self._group)
        scroller.set_child(clamp)
        toolbar_view.set_content(scroller)
        self.set_child(toolbar_view)

        for locale, value in values.items():
            self._add_row(locale, value)
        if None not in values:
            self._add_row(None, "")

    def _add_row(self, locale, value):
        title = "Default (no locale)" if locale is None else locale
        row = Adw.EntryRow(title=title)
        row.set_text(value or "")
        if locale is not None:
            remove_btn = Gtk.Button(icon_name="user-trash-symbolic", valign=Gtk.Align.CENTER)
            remove_btn.add_css_class("flat")
            remove_btn.connect("clicked", lambda *_: self._remove_row(locale))
            row.add_suffix(remove_btn)
        self._group.add(row)
        self._rows[locale] = row

    def _remove_row(self, locale):
        row = self._rows.pop(locale, None)
        if row:
            self._group.remove(row)

    def _on_add_locale(self, *_a):
        dialog = Adw.AlertDialog(
            heading="Add Locale",
            body="Enter a locale code, e.g. fr, de_DE, pt_BR or es@valencia.",
        )
        entry = Gtk.Entry()
        entry.set_placeholder_text("fr")
        dialog.set_extra_child(entry)
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("add", "Add")
        dialog.set_response_appearance("add", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("add")

        def on_response(_d, response):
            if response == "add":
                locale = entry.get_text().strip()
                if locale and locale not in self._rows:
                    self._add_row(locale, "")

        dialog.connect("response", on_response)
        dialog.present(self)

    def get_values(self):
        """Returns an OrderedDict {locale_or_None: text}, omitting blanks
        (except the default may be empty, meaning 'no default value')."""
        from collections import OrderedDict
        result = OrderedDict()
        # default first
        if None in self._rows:
            text = self._rows[None].get_text()
            if text:
                result[None] = text
        for locale, row in self._rows.items():
            if locale is None:
                continue
            text = row.get_text()
            if text:
                result[locale] = text
        return result
