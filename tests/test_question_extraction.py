from flashcards.pdf_import.models import DocumentChunk
from flashcards.pdf_import.parser import DoclingPdfParser
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


def test_preserves_multiple_choice_options_and_resolves_letter_answer_key():
    text = "1. Which chamber receives blood?\nA. Left ventricle\nB. Right atrium\nAnswer: B"
    card = extract_questions(chunk(text))[0]
    assert card.options == ["Left ventricle", "Right atrium"]
    assert card.answer == "Right atrium"


def test_extracts_wrapped_numbered_question_with_choices():
    text = (
        "13. Which statement about neural tube defects\n"
        "is correct?\n"
        "a. First answer\n"
        "b. Correct answer\n"
        "c. Third answer\n"
        "Answer: b"
    )
    card = extract_questions(chunk(text))[0]
    assert card.question == "Which statement about neural tube defects is correct?"
    assert card.options == ["First answer", "Correct answer", "Third answer"]
    assert card.answer == "Correct answer"


def test_parser_adds_answer_key_for_highlighted_option():
    text = "a. First option\nb. Correct option"
    marked = DoclingPdfParser._mark_highlighted_answers(text, {"correct option"})
    assert "b. Correct option\nAnswer: Correct option" in marked


def test_highlighted_answer_key_is_added_after_all_choices():
    text = "a. First option\nb. Correct option\nc. Third option\nd. Fourth option"
    marked = DoclingPdfParser._mark_highlighted_answers(text, {"correct option"})
    assert marked.endswith("d. Fourth option\nAnswer: Correct option")
    card = extract_questions(chunk(f"1. Which is correct?\n{marked}"))[0]
    assert card.options == ["First option", "Correct option", "Third option", "Fourth option"]
    assert card.answer == "Correct option"


def test_does_not_accept_arbitrary_question_mark_without_context():
    cards = extract_questions(chunk("Could this be incidental?", section="Discussion"))
    assert cards == []


def test_missing_answer_is_never_invented():
    card = extract_questions(chunk("Question: What is preload?"))[0]
    assert card.answer == ""
    assert card.requires_input is True


def test_question_promoted_to_docling_section_heading_is_extracted():
    source = (
        "Answer: It verifies that DNA replication is complete and that unresolved DNA damage is\n"
        "not carried into mitosis."
    )
    heading_chunk = DocumentChunk(
        "doc-2", "doc", 2, "Q: What is the main purpose of the G2 checkpoint?", "", source, 2, 2
    )

    cards = extract_questions(heading_chunk)

    assert len(cards) == 1
    assert cards[0].question == "What is the main purpose of the G2 checkpoint?"
    assert cards[0].answer == (
        "It verifies that DNA replication is complete and that unresolved DNA damage is "
        "not carried into mitosis."
    )
    assert cards[0].requires_input is False


def test_numbered_question_promoted_to_heading_is_extracted():
    heading_chunk = DocumentChunk(
        "doc-3",
        "doc",
        3,
        "4. Why does checkpoint loss increase genomic instability?",
        "",
        "Answer: Damaged cells continue dividing.",
        4,
        4,
    )

    cards = extract_questions(heading_chunk)

    assert [card.question for card in cards] == ["Why does checkpoint loss increase genomic instability?"]
