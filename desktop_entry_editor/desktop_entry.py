"""
desktop_entry.py

A faithful, order- and comment-preserving reader/writer for freedesktop.org
"Desktop Entry" files (.desktop / .directory), implementing the Desktop
Entry Specification:
https://specifications.freedesktop.org/desktop-entry-spec/latest/

This module has no GTK / GUI dependency so it can be used and tested
standalone.
"""
from __future__ import annotations

import re
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Optional

MAIN_GROUP = "Desktop Entry"
ACTION_GROUP_PREFIX = "Desktop Action "

# ---------------------------------------------------------------------------
# Spec metadata: which keys exist, their types, and how they should be
# treated (boolean / string-list / localestring / etc). This drives both
# parsing (value escaping) and the GUI (which widget to use).
# ---------------------------------------------------------------------------

BOOLEAN_KEYS = {
    "NoDisplay", "Hidden", "DBusActivatable", "Terminal", "StartupNotify",
    "PrefersNonDefaultGPU", "SingleMainWindow",
}

LIST_KEYS = {
    "OnlyShowIn", "NotShowIn", "Actions", "MimeType", "Categories",
    "Implements", "Keywords",
}

# Keys whose values are "localestring" and therefore may appear with a
# [LOCALE] suffix, e.g. Name[fr]=Ouvrir
LOCALIZABLE_KEYS = {"Name", "GenericName", "Comment", "Keywords"}

STRING_ESCAPE_KEYS = {"Exec", "TryExec"}

TYPE_CHOICES = ["Application", "Link", "Directory"]

MAIN_CATEGORIES = [
    "AudioVideo", "Audio", "Video", "Development", "Education", "Game",
    "Graphics", "Network", "Office", "Science", "Settings", "System",
    "Utility",
]

ADDITIONAL_CATEGORIES = [
    "Building", "Debugger", "IDE", "GUIDesigner", "Profiling",
    "RevisionControl", "Translation", "Calendar", "ContactManagement",
    "Database", "Dictionary", "Chart", "Email", "Finance", "FlowChart",
    "PDA", "ProjectManagement", "Presentation", "Spreadsheet",
    "WordProcessor", "Scanning", "OCR", "Photography", "Publishing",
    "Viewer", "TextTools", "DesktopSettings", "HardwareSettings",
    "Printing", "PackageManager", "Dialup", "InstantMessaging", "Chat",
    "IRCClient", "Feed", "FileTransfer", "HamRadio", "News", "P2P",
    "RemoteAccess", "Telephony", "TelephonyTools", "VideoConference",
    "WebBrowser", "WebDevelopment", "Midi", "Mixer", "Sequencer",
    "Tuner", "TV", "AudioVideoEditing", "Player", "Recorder",
    "DiscBurning", "ActionGame", "AdventureGame", "ArcadeGame",
    "BoardGame", "BlocksGame", "CardGame", "KidsGame", "LogicGame",
    "RolePlaying", "Shooter", "Simulation", "SportsGame",
    "StrategyGame", "Art", "Construction", "Music", "Languages",
    "ArtificialIntelligence", "Astronomy", "Biology", "Chemistry",
    "ComputerScience", "DataVisualization", "Economy", "Electricity",
    "Geography", "Geology", "Geoscience", "History", "Humanities",
    "ImageProcessing", "Literature", "Maps", "Math",
    "NumericalAnalysis", "MedicalSoftware", "Physics", "Robotics",
    "Spirituality", "Sports", "ParallelComputing", "Amusement",
    "Archiving", "Compression", "Electronics", "Emulator", "Engineering",
    "FileTools", "FileManager", "TerminalEmulator", "Filesystem",
    "Monitor", "Security", "Accessibility", "Calculator", "Clock",
    "TextEditor", "Documentation", "Adult", "Core", "KDE", "GNOME",
    "XFCE", "GTK", "Qt", "Motif", "Java", "ConsoleOnly",
]

DESKTOP_ENVIRONMENTS = [
    "GNOME", "KDE", "LXDE", "LXQt", "MATE", "Razor", "ROX", "TDE",
    "Unity", "XFCE", "EDE", "Cinnamon", "Pantheon", "Old",
]

_GROUP_RE = re.compile(r"^\[(?P<name>.+)\]\s*$")
_KV_RE = re.compile(r"^(?P<key>[A-Za-z0-9-]+)(\[(?P<locale>[^\]]+)\])?\s*=\s*(?P<value>.*)$")


def unescape_value(raw: str) -> str:
    """Undo the backslash escaping used in string/localestring values."""
    out = []
    i = 0
    n = len(raw)
    while i < n:
        c = raw[i]
        if c == "\\" and i + 1 < n:
            nxt = raw[i + 1]
            if nxt == "s":
                out.append(" ")
                i += 2
                continue
            if nxt == "n":
                out.append("\n")
                i += 2
                continue
            if nxt == "t":
                out.append("\t")
                i += 2
                continue
            if nxt == "r":
                out.append("\r")
                i += 2
                continue
            if nxt == "\\":
                out.append("\\")
                i += 2
                continue
            if nxt == ";":
                out.append(";")
                i += 2
                continue
        out.append(c)
        i += 1
    return "".join(out)


def escape_value(value: str, is_list: bool = False) -> str:
    """Escape a value for writing back out to a .desktop file."""
    value = value.replace("\\", "\\\\")
    value = value.replace("\n", "\\n").replace("\t", "\\t").replace("\r", "\\r")
    if is_list:
        value = value.replace(";", "\\;")
    return value


def parse_list_value(raw: str) -> list[str]:
    """Split a semicolon-separated list value, honouring \\; escapes."""
    items: list[str] = []
    current = []
    i = 0
    n = len(raw)
    while i < n:
        c = raw[i]
        if c == "\\" and i + 1 < n and raw[i + 1] == ";":
            current.append(";")
            i += 2
            continue
        if c == ";":
            item = "".join(current)
            if item != "":
                items.append(unescape_value(item))
            current = []
            i += 1
            continue
        current.append(c)
        i += 1
    tail = "".join(current)
    if tail.strip() != "":
        items.append(unescape_value(tail))
    return items


def format_list_value(items: list[str]) -> str:
    if not items:
        return ""
    parts = [escape_value(i, is_list=True) for i in items]
    return ";".join(parts) + ";"


# ---------------------------------------------------------------------------
# Line-level model: each group keeps its content as an ordered list of
# entries so that comments, blank lines and key ordering are preserved
# exactly when the file is re-serialised.
# ---------------------------------------------------------------------------

@dataclass
class _Line:
    kind: str  # "comment" | "blank" | "kv"
    raw: str = ""          # for comment lines
    key: str = ""          # base key, e.g. "Name"
    locale: Optional[str] = None
    value: str = ""        # raw (still-escaped) value


class Group:
    """A single [Group] section of a .desktop file."""

    def __init__(self, name: str):
        self.name = name
        self.lines: list[_Line] = []

    # -- low level -----------------------------------------------------
    def _find(self, key: str, locale: Optional[str]) -> Optional[_Line]:
        for ln in self.lines:
            if ln.kind == "kv" and ln.key == key and ln.locale == locale:
                return ln
        return None

    def full_key_name(self, key: str, locale: Optional[str]) -> str:
        return f"{key}[{locale}]" if locale else key

    # -- public API ------------------------------------------------------
    def get_raw(self, key: str, locale: Optional[str] = None, default: str = "") -> str:
        ln = self._find(key, locale)
        return ln.value if ln else default

    def get(self, key: str, locale: Optional[str] = None, default: str = "") -> str:
        raw = self.get_raw(key, locale, default=None)
        if raw is None:
            return default
        return unescape_value(raw)

    def get_bool(self, key: str, default: bool = False) -> bool:
        raw = self.get_raw(key, None, default=None)
        if raw is None:
            return default
        return raw.strip().lower() == "true"

    def get_list(self, key: str, locale: Optional[str] = None) -> list[str]:
        raw = self.get_raw(key, locale, default="")
        return parse_list_value(raw)

    def set(self, key: str, value: str, locale: Optional[str] = None,
            is_list: bool = False) -> None:
        raw_value = value if is_list else escape_value(value)
        ln = self._find(key, locale)
        if ln:
            ln.value = raw_value
        else:
            new_line = _Line(kind="kv", key=key, locale=locale, value=raw_value)
            # Insert before any trailing run of blank lines so new keys stay
            # grouped with existing content rather than after the separator
            # blank that precedes the next section.
            insert_at = len(self.lines)
            while insert_at > 0 and self.lines[insert_at - 1].kind == "blank":
                insert_at -= 1
            self.lines.insert(insert_at, new_line)

    def set_bool(self, key: str, value: bool) -> None:
        self.set(key, "true" if value else "false")

    def set_list(self, key: str, items: list[str], locale: Optional[str] = None) -> None:
        if not items:
            self.delete(key, locale)
            return
        self.set(key, format_list_value(items), locale=locale, is_list=True)

    def delete(self, key: str, locale: Optional[str] = None) -> None:
        self.lines = [
            ln for ln in self.lines
            if not (ln.kind == "kv" and ln.key == key and ln.locale == locale)
        ]

    def locales_for(self, key: str) -> list[str]:
        """Return every locale for which `key[locale]` exists (not incl. base)."""
        return [ln.locale for ln in self.lines
                if ln.kind == "kv" and ln.key == key and ln.locale]

    def all_keys(self) -> list[str]:
        seen = []
        for ln in self.lines:
            if ln.kind == "kv" and ln.key not in seen:
                seen.append(ln.key)
        return seen

    def to_lines(self) -> list[str]:
        out = [f"[{self.name}]"]
        for ln in self.lines:
            if ln.kind == "comment":
                out.append(ln.raw)
            elif ln.kind == "blank":
                out.append("")
            else:
                name = self.full_key_name(ln.key, ln.locale)
                out.append(f"{name}={ln.value}")
        return out


class DesktopEntryError(Exception):
    pass


class DesktopEntry:
    """Represents a whole .desktop / .directory file."""

    def __init__(self):
        self.header: list[str] = []  # comment/blank lines before the first group
        self.groups: "OrderedDict[str, Group]" = OrderedDict()
        self.path: Optional[str] = None
        # explicit action ordering (mirrors the Actions= key, kept in sync)
        self._action_order: list[str] = []

    # ------------------------------------------------------------------
    # Parsing / serialising
    # ------------------------------------------------------------------
    @classmethod
    def new_application(cls) -> "DesktopEntry":
        entry = cls()
        g = entry.ensure_group(MAIN_GROUP)
        g.set("Type", "Application")
        g.set("Name", "New Application")
        g.set("Exec", "")
        g.set_bool("Terminal", False)
        return entry

    @classmethod
    def from_file(cls, path: str) -> "DesktopEntry":
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
        entry = cls.from_string(text)
        entry.path = path
        return entry

    @classmethod
    def from_string(cls, text: str) -> "DesktopEntry":
        entry = cls()
        current: Optional[Group] = None
        for raw_line in text.splitlines():
            line = raw_line.rstrip("\n")
            stripped = line.strip()
            if stripped == "":
                if current is None:
                    entry.header.append("")
                else:
                    current.lines.append(_Line(kind="blank"))
                continue
            if stripped.startswith("#"):
                if current is None:
                    entry.header.append(line)
                else:
                    current.lines.append(_Line(kind="comment", raw=line))
                continue
            gm = _GROUP_RE.match(stripped)
            if gm:
                name = gm.group("name")
                current = entry.ensure_group(name)
                continue
            kv = _KV_RE.match(line)
            if kv and current is not None:
                current.lines.append(_Line(
                    kind="kv",
                    key=kv.group("key"),
                    locale=kv.group("locale"),
                    value=kv.group("value"),
                ))
                continue
            # Unparseable line: keep it as a comment so nothing is lost.
            target = current.lines if current is not None else entry.header
            target.append(_Line(kind="comment", raw=line) if current is not None else line)
        entry._sync_action_order_from_keys()
        return entry

    def to_string(self) -> str:
        out: list[str] = list(self.header)
        while out and out[-1] == "":
            out.pop()
        for group in self.groups.values():
            if out:
                out.append("")
            out.extend(group.to_lines())
            while out and out[-1] == "":
                out.pop()
        text = "\n".join(out)
        if not text.endswith("\n"):
            text += "\n"
        return text

    def save(self, path: Optional[str] = None) -> None:
        target = path or self.path
        if not target:
            raise DesktopEntryError("No path given to save to.")
        with open(target, "w", encoding="utf-8") as f:
            f.write(self.to_string())
        self.path = target

    # ------------------------------------------------------------------
    # Group helpers
    # ------------------------------------------------------------------
    def ensure_group(self, name: str) -> Group:
        if name not in self.groups:
            self.groups[name] = Group(name)
        return self.groups[name]

    @property
    def main(self) -> Group:
        return self.ensure_group(MAIN_GROUP)

    # ------------------------------------------------------------------
    # Actions ([Desktop Action X] sections)
    # ------------------------------------------------------------------
    def _sync_action_order_from_keys(self) -> None:
        declared = self.main.get_list("Actions")
        existing_groups = [
            g.name[len(ACTION_GROUP_PREFIX):]
            for g in self.groups.values()
            if g.name.startswith(ACTION_GROUP_PREFIX)
        ]
        order = [a for a in declared if a in existing_groups]
        for a in existing_groups:
            if a not in order:
                order.append(a)
        self._action_order = order

    def list_actions(self) -> list[str]:
        return list(self._action_order)

    def get_action_group(self, action_id: str) -> Group:
        return self.ensure_group(ACTION_GROUP_PREFIX + action_id)

    def add_action(self, action_id: str, name: str = "New Action",
                   exec_cmd: str = "", icon: str = "") -> None:
        if action_id in self._action_order:
            raise DesktopEntryError(f"Action '{action_id}' already exists.")
        g = self.ensure_group(ACTION_GROUP_PREFIX + action_id)
        g.set("Name", name)
        g.set("Exec", exec_cmd)
        if icon:
            g.set("Icon", icon)
        self._action_order.append(action_id)
        self.main.set_list("Actions", self._action_order)

    def remove_action(self, action_id: str) -> None:
        group_name = ACTION_GROUP_PREFIX + action_id
        if group_name in self.groups:
            del self.groups[group_name]
        if action_id in self._action_order:
            self._action_order.remove(action_id)
        self.main.set_list("Actions", self._action_order)

    def reorder_actions(self, new_order: list[str]) -> None:
        assert set(new_order) == set(self._action_order)
        self._action_order = list(new_order)
        self.main.set_list("Actions", self._action_order)

    def rename_action(self, old_id: str, new_id: str) -> None:
        if old_id == new_id:
            return
        if new_id in self._action_order:
            raise DesktopEntryError(f"Action '{new_id}' already exists.")
        old_group = self.groups.pop(ACTION_GROUP_PREFIX + old_id)
        old_group.name = ACTION_GROUP_PREFIX + new_id
        # rebuild groups OrderedDict preserving position
        new_groups: "OrderedDict[str, Group]" = OrderedDict()
        for gname, g in self.groups.items():
            new_groups[gname] = g
        new_groups[old_group.name] = old_group
        self.groups = new_groups
        idx = self._action_order.index(old_id)
        self._action_order[idx] = new_id
        self.main.set_list("Actions", self._action_order)

    # ------------------------------------------------------------------
    # Localised convenience accessors
    # ------------------------------------------------------------------
    def get_localized_map(self, key: str, group: Optional[Group] = None) -> "OrderedDict[Optional[str], str]":
        """Return {None: default_value, 'fr': ..., 'de_DE': ...} for a
        localestring key."""
        group = group or self.main
        result: "OrderedDict[Optional[str], str]" = OrderedDict()
        base = group.get(key, None, default=None)
        if base is not None:
            result[None] = base
        for locale in group.locales_for(key):
            result[locale] = group.get(key, locale)
        return result

    def set_localized(self, key: str, locale: Optional[str], value: str,
                       group: Optional[Group] = None) -> None:
        group = group or self.main
        if value == "":
            group.delete(key, locale)
        else:
            group.set(key, value, locale=locale)

    def remove_localized(self, key: str, locale: Optional[str],
                          group: Optional[Group] = None) -> None:
        group = group or self.main
        group.delete(key, locale)
