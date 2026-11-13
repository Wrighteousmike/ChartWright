"""Where things live.

Running from the source folder, everything stays inside that folder (handy for development). In a packaged
app the install location is read-only, so working files and your own dictionary words go to the per-user
app-data folder instead.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

FROZEN = bool(getattr(sys, "frozen", False))
ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent)) if FROZEN else Path(__file__).resolve().parent.parent
DATA = ROOT / "data"                       # read-only word lists shipped with the app


def _user_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return base / "ChartWright"


STATE = _user_dir() if FROZEN else ROOT     # per-user, writable
WORK = STATE / ".work"                      # uploads, deleted on exit
RUN = STATE / ".run"                        # port file and logs
USER_WORDS = (STATE / "user_words.txt") if FROZEN else (DATA / "user_words.txt")
