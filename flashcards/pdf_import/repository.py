"""SQLite persistence for PDF jobs, drafts, and explicit approval."""

from __future__ import annotations

import json
import sqlite3
import uuid
from typing import Any

from ..database import connect, now_iso
from .models import DraftFlashcard

ACTIVE_STATUSES = ("uploaded", "parsing", "chunking", "generating", "validating")


def create_job(user_id: int, filename: str, mode: str, kind: str = "flashcards") -> str:
    if mode not in {"extract", "generate"}:
        raise ValueError("Mode must be 'extract' or 'generate'.")
    if kind not in {"flashcards", "mock_exam"}:
        raise ValueError("Invalid PDF output type.")
    job_id = uuid.uuid4().hex
    timestamp = now_iso()
    with connect() as connection:
        connection.execute(
            """INSERT INTO pdf_import_jobs
               (id, user_id, original_filename, mode, kind, status, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, 'uploaded', ?, ?)""",
            (job_id, user_id, filename, mode, kind, timestamp, timestamp),
        )
    return job_id


def active_job_count(user_id: int) -> int:
    placeholders = ",".join("?" for _ in ACTIVE_STATUSES)
    with connect() as connection:
        row = connection.execute(
            f"SELECT COUNT(*) AS count FROM pdf_import_jobs WHERE user_id = ? AND status IN ({placeholders})",
            (user_id, *ACTIVE_STATUSES),
        ).fetchone()
    return int(row["count"])


def get_job(user_id: int, job_id: str) -> sqlite3.Row | None:
    with connect() as connection:
        return connection.execute(
            "SELECT * FROM pdf_import_jobs WHERE id = ? AND user_id = ?", (job_id, user_id)
        ).fetchone()


def update_job(job_id: str, **values: Any) -> None:
    allowed = {
        "status",
        "document_title",
        "progress",
        "total_chunks",
        "processed_chunks",
        "error_message",
        "warnings_json",
        "cancel_requested",
        "completed_at",
    }
    updates = {key: value for key, value in values.items() if key in allowed}
    if not updates:
        return
    updates["updated_at"] = now_iso()
    assignments = ", ".join(f"{key} = ?" for key in updates)
    with connect() as connection:
        connection.execute(
            f"UPDATE pdf_import_jobs SET {assignments} WHERE id = ?", (*updates.values(), job_id)
        )


def request_cancellation(user_id: int, job_id: str) -> bool:
    with connect() as connection:
        cursor = connection.execute(
            """UPDATE pdf_import_jobs SET cancel_requested = 1, updated_at = ?
               WHERE id = ? AND user_id = ? AND status NOT IN ('completed', 'partially_completed', 'failed', 'cancelled')""",
            (now_iso(), job_id, user_id),
        )
    return cursor.rowcount > 0


def cancellation_requested(job_id: str) -> bool:
    with connect() as connection:
        row = connection.execute(
            "SELECT cancel_requested FROM pdf_import_jobs WHERE id = ?", (job_id,)
        ).fetchone()
    return bool(row and row["cancel_requested"])


def save_drafts(job_id: str, user_id: int, cards: list[DraftFlashcard]) -> None:
    timestamp = now_iso()
    with connect() as connection:
        connection.execute("DELETE FROM generated_flashcard_drafts WHERE job_id = ?", (job_id,))
        connection.executemany(
            """INSERT INTO generated_flashcard_drafts
               (job_id, user_id, question, answer, options_json, evidence, page_number, section_title,
                chunk_id, confidence, requires_input, accepted, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)""",
            [
                (
                    job_id,
                    user_id,
                    card.question,
                    card.answer,
                    json.dumps(card.options),
                    card.evidence,
                    card.page_number,
                    card.section_title,
                    card.chunk_id,
                    card.confidence,
                    int(card.requires_input),
                    timestamp,
                    timestamp,
                )
                for card in cards
            ],
        )


def list_drafts(user_id: int, job_id: str) -> list[sqlite3.Row]:
    with connect() as connection:
        return connection.execute(
            """SELECT * FROM generated_flashcard_drafts
               WHERE job_id = ? AND user_id = ? ORDER BY id""",
            (job_id, user_id),
        ).fetchall()


def update_draft(user_id: int, job_id: str, draft_id: int, values: dict[str, Any]) -> bool:
    allowed = {"question", "answer", "accepted"}
    updates = {key: values[key] for key in allowed if key in values}
    if not updates:
        raise ValueError("No editable draft fields were provided.")
    if "question" in updates:
        updates["question"] = str(updates["question"]).strip()
        if not updates["question"] or len(updates["question"]) > 500:
            raise ValueError("Question must contain between 1 and 500 characters.")
    if "answer" in updates:
        updates["answer"] = str(updates["answer"]).strip()
        if len(updates["answer"]) > 1500:
            raise ValueError("Answer must not exceed 1,500 characters.")
        updates["requires_input"] = int(not bool(updates["answer"]))
    if "accepted" in updates:
        updates["accepted"] = int(bool(updates["accepted"]))
    updates["updated_at"] = now_iso()
    assignments = ", ".join(f"{key} = ?" for key in updates)
    with connect() as connection:
        cursor = connection.execute(
            f"""UPDATE generated_flashcard_drafts SET {assignments}
                WHERE id = ? AND job_id = ? AND user_id = ?""",
            (*updates.values(), draft_id, job_id, user_id),
        )
    return cursor.rowcount > 0


def delete_draft(user_id: int, job_id: str, draft_id: int) -> bool:
    with connect() as connection:
        cursor = connection.execute(
            "DELETE FROM generated_flashcard_drafts WHERE id = ? AND job_id = ? AND user_id = ?",
            (draft_id, job_id, user_id),
        )
    return cursor.rowcount > 0


def approve_drafts(user_id: int, job_id: str, deck_name: str) -> int:
    deck_name = deck_name.strip()
    if not deck_name or len(deck_name) > 200:
        raise ValueError("Deck name must contain between 1 and 200 characters.")
    with connect() as connection:
        job = connection.execute(
            "SELECT * FROM pdf_import_jobs WHERE id = ? AND user_id = ?", (job_id, user_id)
        ).fetchone()
        if not job or job["status"] not in {"completed", "partially_completed"}:
            raise ValueError("This PDF import is not ready to save.")
        drafts = connection.execute(
            """SELECT * FROM generated_flashcard_drafts
               WHERE job_id = ? AND user_id = ? AND accepted = 1 ORDER BY id""",
            (job_id, user_id),
        ).fetchall()
        if not drafts:
            raise ValueError("Select at least one draft card to save.")
        if any(not draft["question"].strip() or not draft["answer"].strip() for draft in drafts):
            raise ValueError("Every selected card must have both a question and an answer.")
        if job["kind"] == "mock_exam":
            invalid = []
            for draft in drafts:
                try:
                    options = json.loads(draft["options_json"] or "[]")
                except json.JSONDecodeError:
                    options = []
                if not isinstance(options, list) or len(options) < 2 or draft["answer"] not in options:
                    invalid.append(draft)
            if invalid:
                raise ValueError(
                    "Each selected exam question must have at least two choices and a correct answer matching a choice."
                )
        timestamp = now_iso()
        cursor = connection.execute(
            """INSERT INTO decks (user_id, name, source_filename, card_count, kind, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (user_id, deck_name, job["original_filename"], len(drafts), job["kind"], timestamp),
        )
        deck_id = int(cursor.lastrowid)
        connection.executemany(
            """INSERT INTO cards
               (deck_id, front, back, position, updated_at, evidence, source_page,
                source_section, source_document, generation_mode, options_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                (
                    deck_id,
                    draft["question"],
                    draft["answer"],
                    index,
                    timestamp,
                    draft["evidence"],
                    draft["page_number"],
                    draft["section_title"],
                    job["document_title"],
                    job["mode"],
                    draft["options_json"],
                )
                for index, draft in enumerate(drafts)
            ],
        )
    return deck_id


def serialize_job(job: sqlite3.Row, draft_count: int | None = None) -> dict[str, Any]:
    result = dict(job)
    result["cancel_requested"] = bool(result["cancel_requested"])
    result["warnings"] = json.loads(result.pop("warnings_json") or "[]")
    if draft_count is not None:
        result["draft_count"] = draft_count
    return result


def recover_interrupted_jobs() -> None:
    placeholders = ",".join("?" for _ in ACTIVE_STATUSES)
    with connect() as connection:
        connection.execute(
            f"""UPDATE pdf_import_jobs SET status = 'failed', progress = 100,
                error_message = 'Processing was interrupted when the server stopped.',
                updated_at = ?, completed_at = ? WHERE status IN ({placeholders})""",
            (now_iso(), now_iso(), *ACTIVE_STATUSES),
        )
