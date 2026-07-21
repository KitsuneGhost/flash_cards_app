from pathlib import Path

import pytest

from flashcards.pdf_import.upload import UploadValidationError, temporary_pdf, validate_pdf_upload


def test_pdf_upload_validation_checks_all_signals():
    validate_pdf_upload(b"%PDF-1.7\ndata", "notes.pdf", "application/pdf", 100)
    with pytest.raises(UploadValidationError):
        validate_pdf_upload(b"not pdf", "notes.pdf", "application/pdf", 100)
    with pytest.raises(UploadValidationError):
        validate_pdf_upload(b"%PDF-data", "../notes.exe", "application/pdf", 100)
    with pytest.raises(UploadValidationError):
        validate_pdf_upload(b"%PDF-data", "notes.pdf", "text/plain", 100)


def test_temporary_pdf_is_cleaned_after_success_and_failure():
    captured: Path | None = None
    with pytest.raises(RuntimeError):
        with temporary_pdf(b"%PDF-data") as path:
            captured = path
            assert path.exists()
            assert path.name.startswith("flashcards-pdf-")
            raise RuntimeError("parser failed")
    assert captured is not None
    assert not captured.exists()
