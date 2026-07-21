from flashcards.pdf_import.normalization import normalize_document_text, normalize_for_matching


def test_document_normalization_repairs_hyphenation_and_spacing():
    assert normalize_document_text("cardio-\nvascular   system\r\n\r\nNext") == "cardiovascular system\nNext"


def test_evidence_normalization_handles_unicode_and_punctuation():
    assert normalize_for_matching("Café—valve\n pressure") == "cafe valve pressure"
