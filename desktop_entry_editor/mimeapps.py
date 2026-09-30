"""
mimeapps.py

Backend for the "Default Apps" and "File Types" features. It answers:

  - which application is the default for a MIME type (web browser, mail
    client, PDF viewer, ...)
  - which applications *can* handle a MIME type
  - how do I change / reset that default
  - which file suffixes (.exe, .tar.xz, ...) belong to which MIME type

Reading and writing go through Gio.AppInfo, which is exactly what GNOME
Settings, Nautilus and `xdg-mime` all end up using: changes land in
~/.config/mimeapps.list and are honoured system-wide immediately, with no
root needed. We deliberately do NOT hand-edit mimeapps.list ourselves.

There is no Gtk/Adw dependency here (only Gio/GLib), so this module can be
unit-tested headlessly.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

import gi

from gi.repository import Gio, GLib


# ----------------------------------------------------------------------
# Well-known "default application" categories
# ----------------------------------------------------------------------
@dataclass(frozen=True)
class DefaultAppCategory:
    key: str
    title: str
    icon: str
    # The first type is the "primary" one used to list candidate apps.
    # Changing the default applies to *all* of them together, so e.g.
    # picking a browser sets http, https, html and xhtml in one go.
    mime_types: tuple[str, ...]


CATEGORIES: tuple[DefaultAppCategory, ...] = (
    DefaultAppCategory("browser", "Web Browser", "web-browser-symbolic", (
        "x-scheme-handler/http",
        "x-scheme-handler/https",
        "text/html",
        "application/xhtml+xml",
    )),
    DefaultAppCategory("mail", "Mail", "mail-unread-symbolic", (
        "x-scheme-handler/mailto",
    )),
    DefaultAppCategory("calendar", "Calendar", "x-office-calendar-symbolic", (
        "text/calendar",
        "x-scheme-handler/webcal",
    )),
    DefaultAppCategory("files", "File Manager", "system-file-manager-symbolic", (
        "inode/directory",
    )),
    DefaultAppCategory("text", "Text Editor", "text-editor-symbolic", (
        "text/plain",
    )),
    DefaultAppCategory("pdf", "Documents (PDF)", "x-office-document-symbolic", (
        "application/pdf",
    )),
    DefaultAppCategory("ebook", "E-books", "accessories-dictionary-symbolic", (
        "application/epub+zip",
    )),
    DefaultAppCategory("image", "Photos", "image-x-generic-symbolic", (
        "image/jpeg",
        "image/png",
        "image/gif",
        "image/webp",
    )),
    DefaultAppCategory("music", "Music", "audio-x-generic-symbolic", (
        "audio/mpeg",
        "audio/flac",
        "audio/ogg",
        "audio/x-wav",
    )),
    DefaultAppCategory("video", "Video", "video-x-generic-symbolic", (
        "video/mp4",
        "video/x-matroska",
        "video/webm",
        "video/x-msvideo",
    )),
    DefaultAppCategory("archive", "Archives", "package-x-generic-symbolic", (
        "application/zip",
        "application/x-xz-compressed-tar",
        "application/x-compressed-tar",
        "application/x-tar",
        "application/x-7z-compressed",
        "application/vnd.rar",
    )),
    DefaultAppCategory("contacts", "Contacts", "avatar-default-symbolic", (
        "text/vcard",
        "text/x-vcard",
    )),
    DefaultAppCategory("torrent", "Torrents", "folder-download-symbolic", (
        "application/x-bittorrent",
        "x-scheme-handler/magnet",
    )),
    DefaultAppCategory("maps", "Maps", "mark-location-symbolic", (
        "x-scheme-handler/geo",
    )),
)


def category_by_key(key: str) -> DefaultAppCategory | None:
    for cat in CATEGORIES:
        if cat.key == key:
            return cat
    return None


# ----------------------------------------------------------------------
# Applications
# ----------------------------------------------------------------------
def app_id(app: Gio.AppInfo | None) -> str:
    return (app.get_id() or "") if app is not None else ""


def app_name(app: Gio.AppInfo | None) -> str:
    if app is None:
        return ""
    return app.get_display_name() or app.get_name() or app.get_id() or ""


def _dedup_sorted(apps, keep: Gio.AppInfo | None = None) -> list[Gio.AppInfo]:
    seen: set[str] = set()
    out: list[Gio.AppInfo] = []
    keep_id = app_id(keep)
    for app in apps:
        aid = app_id(app)
        if not aid or aid in seen:
            continue
        # Hide NoDisplay helpers (xdg-open shims and the like), except
        # for the current default: if that is one, it must stay visible.
        if not app.should_show() and aid != keep_id:
            continue
        seen.add(aid)
        out.append(app)
    out.sort(key=lambda a: app_name(a).casefold())
    return out


def get_default(mime: str) -> Gio.AppInfo | None:
    """The app that would currently open `mime`, or None."""
    return Gio.AppInfo.get_default_for_type(mime, False)


def candidates_for(mime: str, include_all: bool = False) -> list[Gio.AppInfo]:
    """Apps that declare support for `mime`. With include_all=True, every
    installed visible app is returned (lets the user force an app that
    doesn't advertise the type, e.g. an editor for .conf files)."""
    current = get_default(mime)
    apps = Gio.AppInfo.get_all() if include_all else Gio.AppInfo.get_all_for_type(mime)
    return _dedup_sorted(apps, keep=current)


def category_state(cat: DefaultAppCategory) -> tuple[Gio.AppInfo | None, bool]:
    """(primary default, mixed). `mixed` is True when the types in the
    category don't all share one default (e.g. http -> Firefox but
    text/html -> Chromium)."""
    defaults = [get_default(m) for m in cat.mime_types]
    primary = defaults[0]
    mixed = any(app_id(d) != app_id(primary) for d in defaults[1:])
    return primary, mixed


def category_candidates(cat: DefaultAppCategory) -> list[Gio.AppInfo]:
    """Candidates for a category: apps handling the primary type, plus
    the current default even if it doesn't advertise the primary type."""
    apps = candidates_for(cat.mime_types[0])
    primary, _mixed = category_state(cat)
    if primary is not None and app_id(primary) not in {app_id(a) for a in apps}:
        apps.append(primary)
        apps.sort(key=lambda a: app_name(a).casefold())
    return apps


def set_default(app: Gio.AppInfo, mime_types) -> list[str]:
    """Make `app` the default for every type in `mime_types`. Returns a
    list of human-readable error strings (empty on full success)."""
    errors: list[str] = []
    for mime in mime_types:
        try:
            if not app.set_as_default_for_type(mime):
                errors.append(f"{mime}: could not be set")
        except GLib.Error as e:
            errors.append(f"{mime}: {e.message}")
    return errors


def reset_defaults(mime_types) -> list[str]:
    """Drop the user's own overrides for these types so the system
    default applies again."""
    errors: list[str] = []
    for mime in mime_types:
        try:
            Gio.AppInfo.reset_type_associations(mime)
        except GLib.Error as e:
            errors.append(f"{mime}: {e.message}")
    return errors


# ----------------------------------------------------------------------
# Suffix <-> MIME
# ----------------------------------------------------------------------
def _xdg_data_home() -> str:
    return os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")


def _xdg_data_dirs() -> list[str]:
    raw = os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share"
    return [d for d in raw.split(":") if d]


def _globs2_files() -> list[str]:
    dirs = [_xdg_data_home()] + _xdg_data_dirs()
    return [os.path.join(d, "mime", "globs2") for d in dirs
            if os.path.isfile(os.path.join(d, "mime", "globs2"))]


def normalize_suffix(text: str) -> str:
    """'*.TAR.XZ' / '.tar.xz' / 'tar.xz' -> 'tar.xz'"""
    t = text.strip().lower()
    if t.startswith("*"):
        t = t[1:]
    return t.lstrip(".")


def load_suffix_index(files: list[str] | None = None) -> dict[str, list[str]]:
    """{mime_type: [suffix, ...]} from the shared-mime-info glob database
    (multi-part suffixes such as 'tar.xz' are supported). Only plain
    '*.suffix' globs are used; patterns like 'Makefile' or 'README*' are
    not suffixes and are skipped."""
    index: dict[str, list[str]] = {}
    for path in (files if files is not None else _globs2_files()):
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                lines = f.read().splitlines()
        except OSError:
            continue
        for line in lines:
            if not line or line.startswith("#"):
                continue
            parts = line.split(":")
            if len(parts) < 3:
                continue
            mime, glob = parts[1], parts[2]
            if not glob.startswith("*."):
                continue
            suffix = glob[2:].lower()
            if not suffix or any(c in suffix for c in "*?[]"):
                continue
            bucket = index.setdefault(mime, [])
            if suffix not in bucket:
                bucket.append(suffix)
    return index


def disambiguate_suffixes(index: dict[str, list[str]]) -> dict[str, list[str]]:
    """Several MIME types can claim the same suffix (.iso is claimed by 7,
    .py by 2, .html by 2). Only one of them is what the system really
    picks for a file with that suffix, so changing the default of the
    others would look like it "did nothing". Keep each suffix only under
    the type Gio resolves it to; types left with no suffix are dropped.
    If Gio picks something we don't list, the suffix is left untouched."""
    owners: dict[str, list[str]] = {}
    for mime, suffixes in index.items():
        for s in suffixes:
            owners.setdefault(s, []).append(mime)
    keep: dict[str, str] = {}
    for s, mimes in owners.items():
        if len(mimes) < 2:
            continue
        winner, _u = Gio.content_type_guess(f"file.{s}", None)
        if winner in mimes:
            keep[s] = winner
    out: dict[str, list[str]] = {}
    for mime, suffixes in index.items():
        kept = [s for s in suffixes if keep.get(s, mime) == mime]
        if kept:
            out[mime] = kept
    return out


def mime_for_suffix(text: str) -> str | None:
    """Best MIME type for a suffix typed by the user, or None if the
    system has no idea about it."""
    suffix = normalize_suffix(text)
    if not suffix or "/" in suffix:
        return None
    mime, _uncertain = Gio.content_type_guess(f"file.{suffix}", None)
    if not mime or mime == "application/octet-stream":
        return None
    return mime


def describe(mime: str) -> str:
    return Gio.content_type_get_description(mime) or mime


def user_customized_types() -> set[str]:
    """MIME types that have an explicit default in the user's own
    ~/.config/mimeapps.list."""
    path = os.path.join(
        os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"),
        "mimeapps.list")
    kf = GLib.KeyFile()
    try:
        kf.load_from_file(path, GLib.KeyFileFlags.NONE)
        keys, _n = kf.get_keys("Default Applications")
    except GLib.Error:
        return set()
    return set(keys)
