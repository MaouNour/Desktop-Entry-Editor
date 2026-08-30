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

import json
import os
from dataclasses import dataclass, field, asdict
from typing import Optional

from .desktop_entry import DesktopEntry, MAIN_CATEGORIES

APPLICATIONS = "applications"
_CACHE_VERSION = 2


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
    at Foo/bar.desktop has id 'Foo-bar.desktop').

    Guards against symlink cycles: os.walk(followlinks=True) does not
    track visited directories on its own (the stdlib docs warn about
    this explicitly), so a symlink that loops back on a parent — not
    uncommon in Flatpak/Snap export trees — makes it recurse until the
    OS's own symlink-resolution limit kicks in. That's slow (each
    failed resolution still costs a syscall) and, depending on how deep
    a real filesystem lets it get before erroring, has been observed to
    make the C stack of a background thread blow up rather than raise
    a catchable Python exception. Tracking realpath(dir) and skipping
    anything already seen makes this a hard guarantee instead of relying
    on the OS to eventually give up.
    """
    seen_real_dirs: set[str] = set()
    # .desktop trees are 1-2 levels deep in every real layout; this is
    # only a last-resort backstop in case a loop somehow isn't caught
    # by the realpath check (e.g. a directory that's re-created with
    # new content between visits).
    max_depth = 12

    def walk(dir_path: str, depth: int):
        if depth > max_depth:
            return
        try:
            real = os.path.realpath(dir_path)
        except OSError:
            return
        if real in seen_real_dirs:
            return
        seen_real_dirs.add(real)

        try:
            entries = list(os.scandir(dir_path))
        except OSError:
            return

        rel_root = os.path.relpath(dir_path, base_dir)
        for entry in entries:
            try:
                is_dir = entry.is_dir(follow_symlinks=True)
            except OSError:
                continue
            if is_dir:
                walk(entry.path, depth + 1)
                continue
            fn = entry.name
            if not (fn.endswith(".desktop") or fn.endswith(".directory")):
                continue
            if rel_root == ".":
                desktop_id = fn
            else:
                desktop_id = rel_root.replace(os.sep, "-") + "-" + fn
            yield desktop_id, entry.path

    yield from walk(base_dir, 0)


def _cache_dir() -> str:
    base = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
    return os.path.join(base, "desktop-entry-editor")


def _cache_path() -> str:
    return os.path.join(_cache_dir(), "scan-cache.json")


def _info_to_cache_dict(info: DesktopFileInfo, mtime: float, size: int) -> dict:
    d = asdict(info)
    d["mtime"] = mtime
    d["size"] = size
    return d


def _dict_to_info(d: dict) -> DesktopFileInfo:
    return DesktopFileInfo(
        path=d["path"], desktop_id=d["desktop_id"], source=d.get("source", "System"),
        writable=d.get("writable", True), name=d.get("name") or d["desktop_id"],
        generic_name=d.get("generic_name", ""), comment=d.get("comment", ""),
        icon=d.get("icon", ""), categories=list(d.get("categories") or []),
        entry_type=d.get("entry_type", "Application"), nodisplay=d.get("nodisplay", False),
        hidden=d.get("hidden", False), exec_cmd=d.get("exec_cmd", ""), error=d.get("error"),
    )


def _read_cache() -> dict:
    try:
        with open(_cache_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    if data.get("version") != _CACHE_VERSION:
        return {}
    return data.get("entries", {})


def _write_cache(entries: dict) -> None:
    # Caching is a pure optimization: never let a write failure (e.g. a
    # read-only home directory) break scanning itself.
    try:
        os.makedirs(_cache_dir(), exist_ok=True)
        tmp = _cache_path() + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"version": _CACHE_VERSION, "entries": entries}, f)
        os.replace(tmp, _cache_path())
    except OSError:
        pass


def load_cached_infos() -> list[DesktopFileInfo]:
    """Return whatever was cached from the last scan_all() call, instantly
    and without touching every desktop file on disk. Meant to paint the
    Browser immediately on launch while a fresh scan runs in the
    background — makes repeat launches feel instant instead of waiting
    on a few hundred file parses every time."""
    entries = _read_cache()
    infos = [_dict_to_info(d) for d in entries.values()]
    infos.sort(key=lambda i: (i.name or i.desktop_id).lower())
    return infos


def scan_all(use_cache: bool = True) -> list[DesktopFileInfo]:
    """Scan every known applications directory and return one
    DesktopFileInfo per unique desktop-file id, already shadow-resolved
    and sorted by display name.

    Directory walking + stat()ing every candidate file is cheap; actually
    parsing a .desktop file is the expensive part. So with use_cache=True
    (the default) a file is only re-parsed if its mtime/size changed
    since the last scan — everything else is served straight from the
    on-disk cache, which makes repeat scans close to instant."""
    seen_ids: set[str] = set()
    seen_real_dirs: set[str] = set()
    candidates: list[tuple[str, str, str]] = []  # (desktop_id, path, source)

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
            candidates.append((desktop_id, path, label))

    old_cache = _read_cache() if use_cache else {}
    results: list[DesktopFileInfo] = []
    new_cache: dict = {}

    for desktop_id, path, source in candidates:
        try:
            st = os.stat(path)
            mtime, size = st.st_mtime, st.st_size
        except OSError:
            continue

        cached = old_cache.get(desktop_id)
        if (use_cache and cached and cached.get("path") == path
                and cached.get("mtime") == mtime and cached.get("size") == size):
            info = _dict_to_info(cached)
            # Permissions can change without the file's content changing,
            # so re-check that cheaply rather than trusting the cache.
            info.writable = os.access(path, os.W_OK)
        else:
            info = _load_info(desktop_id, path, source)

        results.append(info)
        new_cache[desktop_id] = _info_to_cache_dict(info, mtime, size)

    if use_cache:
        _write_cache(new_cache)

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
