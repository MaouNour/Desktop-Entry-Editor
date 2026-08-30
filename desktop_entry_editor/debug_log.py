"""
debug_log.py

A tiny, dependency-free logger for tracking down exactly where a freeze
or crash happens. Every call is written immediately (flushed to disk)
so that even if the process hangs or is killed a moment later, the log
on disk already has the last thing that happened before that — which a
"Segmentation fault" or a force-quit from the desktop's "not responding"
dialog otherwise gives you zero information about.

Not wired into normal operation beyond a handful of key transition
points (window creation, file loading, page building) — cheap enough to
leave in permanently, verbose enough to actually localize a freeze.
"""
from __future__ import annotations

import os
import time

_ENABLED = os.environ.get("DESKTOP_ENTRY_EDITOR_DEBUG", "1") != "0"


def _log_path() -> str:
    base = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
    d = os.path.join(base, "desktop-entry-editor")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "debug.log")


def log(msg: str) -> None:
    if not _ENABLED:
        return
    line = f"{time.strftime('%H:%M:%S')}.{int(time.time() * 1000) % 1000:03d} {msg}"
    try:
        with open(_log_path(), "a", encoding="utf-8") as f:
            f.write(line + "\n")
            f.flush()
            os.fsync(f.fileno())
    except OSError:
        pass
    # Also to stderr — useful when running from a terminal, and shows
    # up immediately even if the log file write above ever fails.
    print(f"[desktop-entry-editor] {line}", flush=True)
