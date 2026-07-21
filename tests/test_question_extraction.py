from flashcards.pdf_import.models import DocumentChunk
from flashcards.pdf_import.question_extraction import extract_questions


def chunk(text, section="Review Questions"):
    return DocumentChunk("doc-0", "doc", 0, section, "", text, 4, 4)


def test_extracts_explicit_question_and_answer_pair():
    cards = extract_questions(chunk("Q: What separates the chambers?\nA: The valve."))
    assert [(card.question, card.answer) for card in cards] == [
        ("What separates the chambers?", "The valve.")
    ]
    assert cards[0].requires_input is False


def test_extracts_multiple_choice_with_source_evidence():
    text = "1. Which structure is shown?\nA. Atrium\nB. Ventricle\nC. Aorta\nAnswer: Aorta"
    card = extract_questions(chunk(text))[0]
    assert card.answer == "Aorta"
    assert "B. Ventricle" in card.evidence


def test_does_not_accept_arbitrary_question_mark_without_context():
    cards = extract_questions(chunk("Could this be incidental?", section="Discussion"))
    assert cards == []


def test_missing_answer_is_never_invented():
    card = extract_questions(chunk("Question: What is preload?"))[0]
    assert card.answer == ""
    assert card.requires_input is True
