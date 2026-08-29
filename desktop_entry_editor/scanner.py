"""
scanner.py

Locates and indexes every installed .desktop / .directory file on the
system, following the XDG Base Directory rules (XDG_DATA_HOME first,
then XDG_DATA_DIRS in order) plus the common Flatpak / Snap export
locations. Implements the spec's "desktop file id" shadowing rule: the
first file found for a given id wins and later ones with the same id
are hidden (that's what makes a copy in ~/.local/share/applications
"override" the system one of the same name).

No GTK dependency, so it can be unit tested / reused headlessly.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional

from .desktop_entry import DesktopEntry, MAIN_CATEGORIES

APPLICATIONS = "applications"


@dataclass
class DesktopFileInfo:
    path: str
    desktop_id: str
    source: str            # human label: "User", "System", "Flatpak", "Snap"
    writable: bool          # can this exact file be saved-in-place right now
    name: str = ""
    generic_name: str = ""
    comment: str = ""
    icon: str = ""
    categories: list[str] = field(default_factory=list)
    entry_type: str = "Application"
    nodisplay: bool = False
    hidden: bool = False
    exec_cmd: str = ""
    error: Optional[str] = None


def _xdg_data_home() -> str:
    return os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")


def _xdg_data_dirs() -> list[str]:
    raw = os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share"
    return [d for d in raw.split(":") if d]


def user_applications_dir() -> str:
    """The directory new/edited entries should normally be saved into so
    they show up for the current user without root: ~/.local/share/applications."""
    return os.path.join(_xdg_data_home(), APPLICATIONS)


def search_locations() -> list[tuple[str, str]]:
    """Ordered (label, directory) pairs to scan, highest priority first.
    Priority order matches XDG shadowing rules, with Flatpak/Snap export
    dirs appended (their exports are frequently also symlinked into
    XDG_DATA_DIRS, in which case they're simply skipped as duplicates)."""
    locations: list[tuple[str, str]] = []
    locations.append(("User", os.path.join(_xdg_data_home(), APPLICATIONS)))
    for d in _xdg_data_dirs():
        locations.append(("System", os.path.join(d, APPLICATIONS)))
    locations.append(("Flatpak", os.path.expanduser(
        "~/.local/share/flatpak/exports/share/applications")))
    locations.append(("Flatpak", "/var/lib/flatpak/exports/share/applications"))
    locations.append(("Snap", "/var/lib/snapd/desktop/applications"))
    return locations


def _iter_desktop_files(base_dir: str):
    """Yield (desktop_id, full_path) for every .desktop/.directory file
    under base_dir, recursing into subdirectories per the spec (a file
    at Foo/bar.desktop has id 'Foo-bar.desktop')."""
    for root, _dirs, files in os.walk(base_dir, followlinks=True):
        rel_root = os.path.relpath(root, base_dir)
        for fn in files:
            if not (fn.endswith(".desktop") or fn.endswith(".directory")):
                continue
            full = os.path.join(root, fn)
            if rel_root == ".":
                desktop_id = fn
            else:
                desktop_id = rel_root.replace(os.sep, "-") + "-" + fn
            yield desktop_id, full


def scan_all() -> list[DesktopFileInfo]:
    """Scan every known applications directory and return one
    DesktopFileInfo per unique desktop-file id, already shadow-resolved
    and sorted by display name."""
    results: list[DesktopFileInfo] = []
    seen_ids: set[str] = set()
    seen_real_dirs: set[str] = set()

    for label, dirpath in search_locations():
        if not os.path.isdir(dirpath):
            continue
        real_dir = os.path.realpath(dirpath)
        if real_dir in seen_real_dirs:
            continue  # e.g. flatpak export dir already reached via XDG_DATA_DIRS
        seen_real_dirs.add(real_dir)

        for desktop_id, path in _iter_desktop_files(dirpath):
            if desktop_id in seen_ids:
                continue
            seen_ids.add(desktop_id)
            results.append(_load_info(desktop_id, path, label))

    results.sort(key=lambda i: (i.name or i.desktop_id).lower())
    return results


def _load_info(desktop_id: str, path: str, source: str) -> DesktopFileInfo:
    writable = os.access(path, os.W_OK) if os.path.exists(path) else os.access(
        os.path.dirname(path), os.W_OK)
    try:
        entry = DesktopEntry.from_file(path)
        m = entry.main
        return DesktopFileInfo(
            path=path,
            desktop_id=desktop_id,
            source=source,
            writable=writable,
            name=m.get("Name") or desktop_id,
            generic_name=m.get("GenericName"),
            comment=m.get("Comment"),
            icon=m.get("Icon"),
            categories=m.get_list("Categories"),
            entry_type=m.get("Type", default="Application"),
            nodisplay=m.get_bool("NoDisplay"),
            hidden=m.get_bool("Hidden"),
            exec_cmd=m.get("Exec"),
        )
    except Exception as e:  # noqa: BLE001 - surface broken files rather than skip them
        return DesktopFileInfo(
            path=path, desktop_id=desktop_id, source=source, writable=writable,
            name=desktop_id, error=str(e),
        )


def category_counts(infos: list[DesktopFileInfo]) -> "OrderedDict[str, int]":
    """Counts per known Main category, in spec order, only including
    categories that actually have at least one match."""
    from collections import OrderedDict
    counts: "OrderedDict[str, int]" = OrderedDict()
    for cat in MAIN_CATEGORIES:
        n = sum(1 for i in infos if cat in i.categories)
        if n:
            counts[cat] = n
    return counts
