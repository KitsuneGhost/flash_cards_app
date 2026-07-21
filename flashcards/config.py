"""Runtime configuration and project paths."""

from __future__ import annotations

import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "flashcards.sqlite3"
STATIC_DIR = BASE_DIR / "static"

HOST = os.environ.get("FLASHCARDS_HOST", "127.0.0.1")
PORT = int(os.environ.get("FLASHCARDS_PORT", "8000"))
MAX_UPLOAD_BYTES = 100 * 1024 * 1024
SESSION_COOKIE = "flashcards_session"
SESSION_DAYS = 14
