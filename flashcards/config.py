"""Runtime configuration and project paths."""

from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = Path(os.environ.get("FLASHCARDS_DB_PATH", DATA_DIR / "flashcards.sqlite3"))
STATIC_DIR = BASE_DIR / "static"

HOST = os.environ.get("FLASHCARDS_HOST", "127.0.0.1")
PORT = int(os.environ.get("FLASHCARDS_PORT", "8000"))
MAX_UPLOAD_BYTES = 100 * 1024 * 1024
SESSION_COOKIE = "flashcards_session"
SESSION_DAYS = 14


def _int_env(name: str, default: int) -> int:
    return int(os.environ.get(name, str(default)))


def _float_env(name: str, default: float) -> float:
    return float(os.environ.get(name, str(default)))


OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen3:4b")
OLLAMA_TIMEOUT_SECONDS = _int_env("OLLAMA_TIMEOUT_SECONDS", 120)
OLLAMA_MAX_RETRIES = _int_env("OLLAMA_MAX_RETRIES", 2)
OLLAMA_TEMPERATURE = _float_env("OLLAMA_TEMPERATURE", 0.1)

PDF_MAX_SIZE_MB = _int_env("PDF_MAX_SIZE_MB", 50)
PDF_MAX_SIZE_BYTES = PDF_MAX_SIZE_MB * 1024 * 1024
PDF_MAX_PAGES = _int_env("PDF_MAX_PAGES", 500)
PDF_CHUNK_TARGET_WORDS = _int_env("PDF_CHUNK_TARGET_WORDS", 1500)
PDF_CHUNK_OVERLAP_WORDS = _int_env("PDF_CHUNK_OVERLAP_WORDS", 100)
PDF_MAX_CARDS_PER_CHUNK = _int_env("PDF_MAX_CARDS_PER_CHUNK", 10)
PDF_MAX_CHUNKS = _int_env("PDF_MAX_CHUNKS", 100)
PDF_MAX_GENERATED_CARDS = _int_env("PDF_MAX_GENERATED_CARDS", 500)
PDF_MAX_CONCURRENT_JOBS_PER_USER = _int_env("PDF_MAX_CONCURRENT_JOBS_PER_USER", 1)
PDF_WORKER_COUNT = _int_env("PDF_WORKER_COUNT", 2)
