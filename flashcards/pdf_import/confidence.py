"""Transparent application-side quality scoring."""

from __future__ import annotations

import re

from .evidence import answer_support_quality
from .models import DraftFlashcard

SUSPICIOUS_LANGUAGE = re.compile(
    r"\b(probably|possibly|generally|always|never|must be|medical advice|you should|recommended dose)\b",
    re.IGNORECASE,
)
VAGUE_QUESTION = re.compile(r"^(what is this|explain this|what does it mean|describe it)\??$", re.IGNORECASE)


def calculate_confidence(card: DraftFlashcard, duplicate_similarity: float = 0.0) -> float:
    score = 0.15
    score += 0.42 * card.evidence_match_quality
    score += 0.20 * answer_support_quality(card.answer, card.evidence) if card.answer else 0.0
    score += 0.08 if card.question.endswith("?") else 0.03
    score += 0.06 if 3 <= len(card.question.split()) <= 30 else 0.0
    score += 0.06 if 1 <= len(card.answer.split()) <= 80 else 0.0
    score += 0.03 if card.section_title else 0.0
    if VAGUE_QUESTION.match(card.question.strip()):
        score -= 0.18
    if SUSPICIOUS_LANGUAGE.search(f"{card.question} {card.answer}"):
        score -= 0.12
    score -= min(0.20, duplicate_similarity * 0.20)
    if card.requires_input:
        score = min(score, 0.55)
    return round(max(0.0, min(1.0, score)), 2)
