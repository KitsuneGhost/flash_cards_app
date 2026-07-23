"""Deck and study-progress persistence."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from .database import connect, now_iso


def save_import(user_id: int, filename: str, deck_name: str, cards: list[dict[str, Any]]) -> int:
    with connect() as connection:
        cursor = connection.execute(
            """INSERT INTO decks (user_id, name, source_filename, card_count, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (user_id, deck_name, filename, len(cards), now_iso()),
        )
        deck_id = int(cursor.lastrowid)
        connection.executemany(
            """INSERT INTO cards
               (deck_id, source_card_id, source_note_id, front, back, position, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            [
                (
                    deck_id,
                    card["source_card_id"],
                    card["source_note_id"],
                    card["front"],
                    card["back"],
                    card["position"],
                    now_iso(),
                )
                for card in cards
            ],
        )
    return deck_id


def list_decks(user_id: int) -> list[sqlite3.Row]:
    with connect() as connection:
        return connection.execute(
            """SELECT decks.*,
                      COALESCE(SUM(cards.seen_count), 0) AS total_seen,
                      COALESCE(SUM(cards.correct_count), 0) AS total_correct
               FROM decks LEFT JOIN cards ON cards.deck_id = decks.id
               WHERE decks.user_id = ? GROUP BY decks.id
               ORDER BY decks.created_at DESC""",
            (user_id,),
        ).fetchall()


def delete_deck(user_id: int, deck_id: int) -> bool:
    """Delete an owned deck and its cards."""
    with connect() as connection:
        cursor = connection.execute("DELETE FROM decks WHERE id = ? AND user_id = ?", (deck_id, user_id))
    return cursor.rowcount > 0


def get_deck_for_study(user_id: int, deck_id: int) -> tuple[sqlite3.Row, list[sqlite3.Row]]:
    with connect() as connection:
        deck = connection.execute(
            "SELECT * FROM decks WHERE id = ? AND user_id = ?", (deck_id, user_id)
        ).fetchone()
        if not deck:
            raise LookupError("Deck not found")
        cards = connection.execute(
            """SELECT id, front, back, options_json, seen_count, correct_count, wrong_count
               FROM cards WHERE deck_id = ? ORDER BY position, id""",
            (deck_id,),
        ).fetchall()
    return deck, cards


def record_progress(user_id: int, card_id: int, result: str) -> None:
    column = "correct_count" if result == "correct" else "wrong_count"
    with connect() as connection:
        connection.execute(
            f"""UPDATE cards SET seen_count = seen_count + 1,
                       {column} = {column} + 1, last_result = ?, updated_at = ?
                   WHERE id = ? AND deck_id IN
                       (SELECT id FROM decks WHERE user_id = ?)""",
            (result, now_iso(), card_id, user_id),
        )


def grade_exam(user_id: int, deck_id: int, answers: dict[int, int]) -> list[dict[str, Any]]:
    """Grade a mock exam without exposing its answers before submission."""
    with connect() as connection:
        deck = connection.execute(
            "SELECT kind FROM decks WHERE id = ? AND user_id = ?", (deck_id, user_id)
        ).fetchone()
        if not deck or deck["kind"] != "mock_exam":
            raise LookupError("Exam not found")
        cards = connection.execute(
            "SELECT id, front, back, options_json FROM cards WHERE deck_id = ? ORDER BY position, id",
            (deck_id,),
        ).fetchall()

    results = []
    for card in cards:
        try:
            options = json.loads(card["options_json"] or "[]")
        except json.JSONDecodeError:
            options = []
        selected_index = answers.get(card["id"])
        selected = (
            options[selected_index]
            if isinstance(selected_index, int) and 0 <= selected_index < len(options)
            else None
        )
        results.append(
            {
                "card_id": card["id"],
                "question": card["front"],
                "selected": selected,
                "correct_answer": card["back"],
                "correct": selected == card["back"],
            }
        )
    return results
