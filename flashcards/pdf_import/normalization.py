"""Text normalization helpers for PDF and evidence content."""

from __future__ import annotations

import re
import unicodedata


def normalize_document_text(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).replace("\x00", "")
    value = re.sub(r"(?<=\w)-\s*\n\s*(?=\w)", "", value)
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in value.split("\n")]
    return "\n".join(line for line in lines if line).strip()


def normalize_for_matching(value: str) -> str:
    value = normalize_document_text(value).casefold()
    value = unicodedata.normalize("NFKD", value)
    value = "".join(character for character in value if not unicodedata.combining(character))
    value = re.sub(r"[^\w\s]", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def word_tokens(value: str) -> set[str]:
    return set(normalize_for_matching(value).split())
