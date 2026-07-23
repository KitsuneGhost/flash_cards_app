from flashcards.pdf_import.chunking import chunk_document, extraction_chunks
from flashcards.pdf_import.models import Document, DocumentBlock, Section, SourceLocation


def document_with_blocks(*texts):
    blocks = [
        DocumentBlock(text, location=SourceLocation(index + 1, index + 1)) for index, text in enumerate(texts)
    ]
    return Document("doc", "Title", [Section("Heading", 1, blocks)], len(blocks))


def test_heading_metadata_and_pages_are_preserved():
    chunks = chunk_document(document_with_blocks("one two", "three four"), 10, 2)
    assert len(chunks) == 1
    assert chunks[0].section_title == "Heading"
    assert (chunks[0].page_start, chunks[0].page_end) == (1, 2)


def test_chunks_stay_within_target_for_splittable_text():
    chunks = chunk_document(document_with_blocks("one two three. Four five six. Seven eight nine."), 4, 1)
    assert all(len(chunk.text.split()) <= 4 for chunk in chunks)


def test_chunk_context_contains_configured_overlap():
    chunks = chunk_document(document_with_blocks("one two three", "four five six"), 3, 2)
    assert len(chunks) == 2
    assert chunks[1].context_before == "two three"


def test_invalid_overlap_is_rejected():
    try:
        chunk_document(document_with_blocks("text"), 10, 10)
    except ValueError as error:
        assert "overlap" in str(error)
    else:
        raise AssertionError("Expected invalid chunk settings to fail")


def test_extraction_chunks_keep_a_large_page_intact():
    document = document_with_blocks("one two three four", "five six seven eight")

    chunks = extraction_chunks(document)

    assert len(chunks) == 1
    assert chunks[0].text == "one two three four\n\nfive six seven eight"
