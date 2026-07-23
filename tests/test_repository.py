import pytest

from flashcards import auth
from flashcards.pdf_import import repository
from flashcards.pdf_import.models import DraftFlashcard


def make_user(name):
    return auth.create_user(name, "password123")


def test_jobs_and_drafts_are_owner_scoped(isolated_database):
    owner = make_user("owner")
    stranger = make_user("stranger")
    job_id = repository.create_job(owner, "notes.pdf", "extract")
    repository.save_drafts(
        job_id, owner, [DraftFlashcard("Question?", "Answer", "Evidence", 1, "Section", "c", 0.8)]
    )
    assert repository.get_job(owner, job_id) is not None
    assert repository.get_job(stranger, job_id) is None
    assert len(repository.list_drafts(owner, job_id)) == 1
    assert repository.list_drafts(stranger, job_id) == []


def test_only_explicitly_accepted_complete_drafts_are_saved(isolated_database):
    user_id = make_user("student")
    job_id = repository.create_job(user_id, "notes.pdf", "generate")
    cards = [
        DraftFlashcard("Keep?", "Yes", "Keep evidence", 1, "One", "c1", 0.9),
        DraftFlashcard("Reject?", "No", "Reject evidence", 2, "Two", "c2", 0.8),
    ]
    repository.save_drafts(job_id, user_id, cards)
    drafts = repository.list_drafts(user_id, job_id)
    repository.update_draft(user_id, job_id, drafts[1]["id"], {"accepted": False})
    repository.update_job(job_id, status="completed", document_title="Notes")
    deck_id = repository.approve_drafts(user_id, job_id, "Generated notes")
    from flashcards.database import connect

    with connect() as connection:
        saved = connection.execute("SELECT * FROM cards WHERE deck_id = ?", (deck_id,)).fetchall()
    assert len(saved) == 1
    assert saved[0]["front"] == "Keep?"
    assert saved[0]["evidence"] == "Keep evidence"


def test_blank_accepted_answer_blocks_approval(isolated_database):
    user_id = make_user("learner")
    job_id = repository.create_job(user_id, "questions.pdf", "extract")
    repository.save_drafts(
        job_id, user_id, [DraftFlashcard("Question?", "", "Question?", 1, "", "c", 0.4, True)]
    )
    repository.update_job(job_id, status="completed")
    with pytest.raises(ValueError, match="question and an answer"):
        repository.approve_drafts(user_id, job_id, "Questions")


def test_mock_exam_requires_answer_to_match_one_of_its_choices(isolated_database):
    user_id = make_user("exam_user")
    job_id = repository.create_job(user_id, "exam.pdf", "extract", "mock_exam")
    repository.save_drafts(
        job_id,
        user_id,
        [
            DraftFlashcard(
                "Which answer?", "Edited answer", "Evidence", 1, "", "c", 0.8, options=["One", "Two"]
            )
        ],
    )
    repository.update_job(job_id, status="completed")
    with pytest.raises(ValueError, match="matching a choice"):
        repository.approve_drafts(user_id, job_id, "Exam")
