"""Opt-in checks: RUN_LOCAL_INTEGRATION=1 pytest -m integration."""

import os
from pathlib import Path

import pytest

from flashcards.config import OLLAMA_BASE_URL, OLLAMA_MODEL
from flashcards.pdf_import.ollama import OllamaClient
from flashcards.pdf_import.parser import DoclingPdfParser

pytestmark = pytest.mark.integration


@pytest.mark.skipif(os.environ.get("RUN_LOCAL_INTEGRATION") != "1", reason="local integration only")
def test_docling_parses_configured_sample():
    sample = Path(os.environ["PDF_INTEGRATION_SAMPLE"])
    document = DoclingPdfParser(max_pages=10, max_file_size=20 * 1024 * 1024).parse(sample)
    assert document.sections


@pytest.mark.skipif(os.environ.get("RUN_LOCAL_INTEGRATION") != "1", reason="local integration only")
def test_ollama_returns_structured_json():
    client = OllamaClient(OLLAMA_BASE_URL, OLLAMA_MODEL, timeout=120, retries=0, temperature=0)
    result = client.generate(
        "Return JSON only.",
        "Return one item named local.",
        {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        },
    )
    assert "name" in result
