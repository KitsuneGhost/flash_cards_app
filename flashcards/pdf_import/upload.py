"""PDF upload validation and temporary-file lifecycle."""

from __future__ import annotations

import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


class UploadValidationError(ValueError):
    """Raised when an uploaded file cannot safely enter the parser."""


def validate_pdf_upload(content: bytes, filename: str, content_type: str, max_bytes: int) -> None:
    if not content:
        raise UploadValidationError("The uploaded PDF is empty.")
    if len(content) > max_bytes:
        raise UploadValidationError(f"The PDF exceeds the {max_bytes // (1024 * 1024)} MB limit.")
    if Path(filename).suffix.lower() != ".pdf":
        raise UploadValidationError("Only files with a .pdf extension are supported.")
    mime = content_type.split(";", 1)[0].strip().lower()
    if mime not in {"application/pdf", "application/x-pdf"}:
        raise UploadValidationError("The uploaded file does not have a PDF content type.")
    if not content.lstrip().startswith(b"%PDF-"):
        raise UploadValidationError("The uploaded file does not have a valid PDF signature.")


@contextmanager
def temporary_pdf(content: bytes) -> Iterator[Path]:
    descriptor, raw_path = tempfile.mkstemp(prefix="flashcards-pdf-", suffix=".pdf")
    path = Path(raw_path)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
        yield path
    finally:
        path.unlink(missing_ok=True)


def create_temporary_pdf(content: bytes) -> Path:
    """Create a random temporary PDF for asynchronous work; the worker owns cleanup."""
    descriptor, raw_path = tempfile.mkstemp(prefix="flashcards-pdf-", suffix=".pdf")
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(content)
    return Path(raw_path)
