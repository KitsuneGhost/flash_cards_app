from flashcards import auth, decks
from flashcards.database import connect, now_iso


def test_grade_exam_keeps_answers_server_side_and_records_correctness(isolated_database):
    user_id = auth.create_user("exam_student", "password123")
    with connect() as connection:
        deck_id = connection.execute(
            "INSERT INTO decks (user_id, name, source_filename, card_count, kind, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, "Exam", "exam.pdf", 1, "mock_exam", now_iso()),
        ).lastrowid
        card_id = connection.execute(
            "INSERT INTO cards (deck_id, front, back, position, options_json) VALUES (?, ?, ?, ?, ?)",
            (deck_id, "Which?", "Two", 0, '["One", "Two"]'),
        ).lastrowid

    result = decks.grade_exam(user_id, deck_id, {card_id: 1})

    assert result == [
        {
            "card_id": card_id,
            "question": "Which?",
            "selected": "Two",
            "correct_answer": "Two",
            "correct": True,
        }
    ]
