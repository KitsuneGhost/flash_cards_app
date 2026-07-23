from flashcards import auth, decks
from flashcards.database import connect, now_iso


def test_delete_deck_is_owner_scoped_and_cascades_to_cards(isolated_database):
    owner_id = auth.create_user("deck_owner", "password123")
    stranger_id = auth.create_user("deck_stranger", "password123")
    with connect() as connection:
        deck_id = connection.execute(
            "INSERT INTO decks (user_id, name, source_filename, card_count, created_at) VALUES (?, ?, ?, ?, ?)",
            (owner_id, "Delete me", "notes.pdf", 1, now_iso()),
        ).lastrowid
        connection.execute(
            "INSERT INTO cards (deck_id, front, back, position) VALUES (?, ?, ?, ?)",
            (deck_id, "Question", "Answer", 0),
        )

    assert decks.delete_deck(stranger_id, deck_id) is False
    assert decks.delete_deck(owner_id, deck_id) is True

    with connect() as connection:
        assert connection.execute("SELECT * FROM decks WHERE id = ?", (deck_id,)).fetchone() is None
        assert connection.execute("SELECT * FROM cards WHERE deck_id = ?", (deck_id,)).fetchone() is None
