import json

import pytest

from flashcards.pdf_import.confidence import calculate_confidence
from flashcards.pdf_import.duplicates import card_similarity, remove_duplicates
from flashcards.pdf_import.evidence import answer_support_quality, evidence_match_quality
from flashcards.pdf_import.models import DocumentChunk, DraftFlashcard
from flashcards.pdf_import.validation import (
    MalformedModelOutput,
    generated_cards_schema,
    parse_model_output,
    validate_generated_card,
)

SOURCE = "The aortic valve separates the left ventricle from the aorta."
CHUNK = DocumentChunk("doc-0", "doc", 0, "Aortic valve", "", SOURCE, 14, 14)


def card(question="What does the aortic valve separate?", answer="The left ventricle and the aorta."):
    return DraftFlashcard(question, answer, SOURCE, 14, "Aortic valve", "doc-0", evidence_match_quality=1.0)


def test_evidence_matching_prefers_exact_and_tolerates_ocr_spacing():
    assert evidence_match_quality(SOURCE, SOURCE) == 1.0
    assert evidence_match_quality("aortic valve separates the left ventricle", SOURCE) == 1.0
    assert evidence_match_quality("unrelated renal statement", SOURCE) < 0.72


def test_answer_support_is_token_based():
    assert answer_support_quality("left ventricle and aorta", SOURCE) > 0.7
    assert answer_support_quality("kidneys", SOURCE) == 0.0


def test_malformed_model_json_is_rejected():
    with pytest.raises(MalformedModelOutput):
        parse_model_output("```json\nnot-json\n```")


def test_missing_schema_fields_are_rejected():
    with pytest.raises(MalformedModelOutput):
        parse_model_output('{"cards":[{"question":"Valid question?"}]}')


def test_generation_schema_omits_unsupported_string_length_keywords():
    serialized = str(generated_cards_schema())
    assert "minLength" not in serialized
    assert "maxLength" not in serialized


def test_valid_generated_card_receives_trusted_chunk_metadata():
    payload = parse_model_output(
        '{"cards":[{"question":"What does the aortic valve separate?",'
        '"answer":"The left ventricle and the aorta.","evidence":"' + SOURCE + '"}]}'
    )[0]
    validated = validate_generated_card(payload, CHUNK)
    assert validated is not None
    assert validated.page_number == 14
    assert validated.chunk_id == "doc-0"


def test_unsupported_answer_is_rejected():
    payload = parse_model_output(
        '{"cards":[{"question":"What dose is used?","answer":"500 mg","evidence":"' + SOURCE + '"}]}'
    )[0]
    assert validate_generated_card(payload, CHUNK) is None


@pytest.mark.parametrize(
    ("question", "answer"),
    [
        ("Who is the professor in this presentation?", "Professor Smith."),
        ("Who made this document?", "Professor Smith."),
        (
            "How does initiation contribute to tumor development according to the source text?",
            "Initiation induces mutations that persist until additional factors promote proliferation.",
        ),
        ("What does the passage state about the aortic valve?", "It separates two structures."),
        ("How is the aortic valve linked to blood flow?", "It is involved in blood-flow development."),
        ("What is the aortic valve involved in?", "It plays a role in circulation."),
    ],
)
def test_trivial_or_vague_cards_are_rejected(question, answer):
    payload = parse_model_output(
        '{"cards":[{"question":' + json.dumps(question) + ',"answer":' + json.dumps(answer)
        + ',"evidence":' + json.dumps(SOURCE) + '}]}')
    assert validate_generated_card(payload[0], CHUNK) is None


def test_duplicate_detection_keeps_better_card():
    weaker = card()
    weaker.confidence = 0.6
    stronger = card()
    stronger.confidence = 0.9
    assert card_similarity(weaker, stronger) == 1.0
    assert remove_duplicates([weaker, stronger]) == [stronger]


def test_confidence_is_transparent_and_bounded():
    grounded = card()
    unsupported = card(answer="possibly something unrelated")
    unsupported.evidence_match_quality = 0.2
    assert 0 <= calculate_confidence(unsupported) < calculate_confidence(grounded) <= 1
