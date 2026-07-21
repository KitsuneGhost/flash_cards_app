"""Deterministic extraction of existing questions and answers."""

from __future__ import annotations

import re

from .confidence import calculate_confidence
from .evidence import evidence_match_quality
from .models import DocumentChunk, DraftFlashcard

QUESTION_PREFIX = re.compile(r"^(?:Q(?:uestion)?\s*[:.)-]\s*|\d{1,3}[.)]\s+|[-*•]\s+)(.+)$", re.I)
ANSWER_PREFIX = re.compile(r"^(?:A(?:nswer)?\s*[:.)-]\s*|Solution\s*:\s*)(.+)$", re.I)
OPTION_LINE = re.compile(r"^[A-H][.)]\s+.+", re.I)
QUESTION_SECTION = re.compile(r"\b(review questions?|exercises?|quiz|self[- ]?test|question bank)\b", re.I)


def extract_questions(chunk: DocumentChunk) -> list[DraftFlashcard]:
    lines = [line.strip() for line in chunk.text.splitlines() if line.strip()]
    cards: list[DraftFlashcard] = []
    index = 0
    section_signal = bool(QUESTION_SECTION.search(chunk.section_title))
    while index < len(lines):
        line = lines[index]
        prefix_match = QUESTION_PREFIX.match(line)
        question = prefix_match.group(1).strip() if prefix_match else line
        strong_signal = bool(prefix_match) or section_signal
        if not question.endswith("?") or (not strong_signal and not _has_answer_nearby(lines, index)):
            index += 1
            continue

        evidence_lines = [line]
        cursor = index + 1
        while cursor < len(lines) and OPTION_LINE.match(lines[cursor]):
            evidence_lines.append(lines[cursor])
            cursor += 1
        answer = ""
        if cursor < len(lines):
            answer_match = ANSWER_PREFIX.match(lines[cursor])
            if answer_match:
                answer = answer_match.group(1).strip()
                evidence_lines.append(lines[cursor])
                cursor += 1
        evidence = "\n".join(evidence_lines)
        card = DraftFlashcard(
            question=question,
            answer=answer,
            evidence=evidence,
            page_number=chunk.page_start,
            section_title=chunk.section_title,
            chunk_id=chunk.id,
            requires_input=not bool(answer),
            evidence_match_quality=evidence_match_quality(evidence, chunk.text),
        )
        card.confidence = calculate_confidence(card)
        cards.append(card)
        index = cursor if cursor > index + 1 else index + 1
    return cards


def _has_answer_nearby(lines: list[str], index: int) -> bool:
    return any(ANSWER_PREFIX.match(line) for line in lines[index + 1 : index + 4])
