"""SQLite connection management and schema initialization."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

from .config import DATA_DIR, DB_PATH


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(exist_ok=True)
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def init_db() -> None:
    with connect() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS sessions (
                token TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS decks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                name TEXT NOT NULL,
                source_filename TEXT NOT NULL,
                card_count INTEGER NOT NULL DEFAULT 0,
                kind TEXT NOT NULL DEFAULT 'flashcards',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS cards (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                deck_id INTEGER NOT NULL REFERENCES decks(id) ON DELETE CASCADE,
                source_card_id INTEGER,
                source_note_id INTEGER,
                front TEXT NOT NULL,
                back TEXT NOT NULL,
                position INTEGER NOT NULL DEFAULT 0,
                seen_count INTEGER NOT NULL DEFAULT 0,
                correct_count INTEGER NOT NULL DEFAULT 0,
                wrong_count INTEGER NOT NULL DEFAULT 0,
                last_result TEXT,
                updated_at TEXT
            );

            CREATE TABLE IF NOT EXISTS pdf_import_jobs (
                id TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                original_filename TEXT NOT NULL,
                mode TEXT NOT NULL CHECK (mode IN ('extract', 'generate')),
                kind TEXT NOT NULL DEFAULT 'flashcards',
                status TEXT NOT NULL,
                document_title TEXT,
                progress INTEGER NOT NULL DEFAULT 0,
                total_chunks INTEGER NOT NULL DEFAULT 0,
                processed_chunks INTEGER NOT NULL DEFAULT 0,
                error_message TEXT,
                warnings_json TEXT NOT NULL DEFAULT '[]',
                cancel_requested INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                completed_at TEXT
            );

            CREATE TABLE IF NOT EXISTS generated_flashcard_drafts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id TEXT NOT NULL REFERENCES pdf_import_jobs(id) ON DELETE CASCADE,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                question TEXT NOT NULL,
                answer TEXT NOT NULL DEFAULT '',
                options_json TEXT NOT NULL DEFAULT '[]',
                evidence TEXT NOT NULL DEFAULT '',
                page_number INTEGER,
                section_title TEXT NOT NULL DEFAULT '',
                chunk_id TEXT NOT NULL,
                confidence REAL NOT NULL,
                requires_input INTEGER NOT NULL DEFAULT 0,
                accepted INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_pdf_jobs_user ON pdf_import_jobs(user_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_pdf_drafts_job ON generated_flashcard_drafts(job_id, id);
            """
        )
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(decks)")}
        if "user_id" not in columns:
            connection.execute(
                "ALTER TABLE decks ADD COLUMN user_id INTEGER REFERENCES users(id) ON DELETE CASCADE"
            )
        if "kind" not in columns:
            connection.execute("ALTER TABLE decks ADD COLUMN kind TEXT NOT NULL DEFAULT 'flashcards'")
        job_columns = {row["name"] for row in connection.execute("PRAGMA table_info(pdf_import_jobs)")}
        if "kind" not in job_columns:
            connection.execute(
                "ALTER TABLE pdf_import_jobs ADD COLUMN kind TEXT NOT NULL DEFAULT 'flashcards'"
            )
        draft_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(generated_flashcard_drafts)")
        }
        if "options_json" not in draft_columns:
            connection.execute(
                "ALTER TABLE generated_flashcard_drafts ADD COLUMN options_json TEXT NOT NULL DEFAULT '[]'"
            )
        card_columns = {row["name"] for row in connection.execute("PRAGMA table_info(cards)")}
        additions = {
            "evidence": "TEXT",
            "source_page": "INTEGER",
            "source_section": "TEXT",
            "source_document": "TEXT",
            "generation_mode": "TEXT",
            "options_json": "TEXT",
        }
        for name, column_type in additions.items():
            if name not in card_columns:
                connection.execute(f"ALTER TABLE cards ADD COLUMN {name} {column_type}")
