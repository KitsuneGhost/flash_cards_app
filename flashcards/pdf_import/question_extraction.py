"""Deterministic extraction of existing questions and answers."""

from __future__ import annotations

import re

from .confidence import calculate_confidence
from .evidence import evidence_match_quality
from .models import DocumentChunk, DraftFlashcard

QUESTION_PREFIX = re.compile(r"^(?:Q(?:uestion)?\s*[:.)-]\s*|\d{1,3}[.)]\s+|[-*•]\s+)(.+)$", re.I)
ANSWER_PREFIX = re.compile(r"^(?:A(?:nswer)?\s*[:.)-]\s*|Solution\s*:\s*)(.+)$", re.I)
OPTION_LINE = re.compile(r"^(?P<label>[A-H])[.)]\s+(?P<text>.+)", re.I)
QUESTION_SECTION = re.compile(r"\b(review questions?|exercises?|quiz|self[- ]?test|question bank)\b", re.I)


def extract_questions(chunk: DocumentChunk) -> list[DraftFlashcard]:
    lines = [line.strip() for line in chunk.text.splitlines() if line.strip()]
    cards: list[DraftFlashcard] = []

    # Docling commonly promotes visually emphasized questions to section
    # headings, leaving the corresponding answer in the section body.
    heading_match = QUESTION_PREFIX.match(chunk.section_title)
    heading_question = heading_match.group(1).strip() if heading_match else chunk.section_title.strip()
    if heading_match and heading_question.endswith("?"):
        answer, answer_lines, _ = _consume_answer(lines, 0)
        cards.append(_draft(chunk, heading_question, answer, [chunk.section_title, *answer_lines]))

    index = 0
    section_signal = bool(QUESTION_SECTION.search(chunk.section_title))
    while index < len(lines):
        line = lines[index]
        prefix_match = QUESTION_PREFIX.match(line)
        question = prefix_match.group(1).strip() if prefix_match else line
        strong_signal = bool(prefix_match) or section_signal
        cursor = index + 1
        question_parts = [question]
        # PDF text frequently wraps a numbered question before its A–H list.
        # Keep collecting those lines, but never consume another question, an
        # answer key, or an answer option as part of the question itself.
        while cursor < len(lines) and not (
            OPTION_LINE.match(lines[cursor])
            or ANSWER_PREFIX.match(lines[cursor])
            or QUESTION_PREFIX.match(lines[cursor])
        ):
            question_parts.append(lines[cursor])
            cursor += 1
        question = " ".join(question_parts)
        has_options = cursor < len(lines) and bool(OPTION_LINE.match(lines[cursor]))
        if not (question.endswith("?") or has_options) or (
            not strong_signal and not _has_answer_nearby(lines, index)
        ):
            index += 1
            continue

        evidence_lines = lines[index:cursor]
        options: list[str] = []
        while cursor < len(lines):
            option_match = OPTION_LINE.match(lines[cursor])
            if option_match:
                evidence_lines.append(lines[cursor])
                options.append(option_match.group("text").strip())
                cursor += 1
            elif (
                options
                and not ANSWER_PREFIX.match(lines[cursor])
                and not QUESTION_PREFIX.match(lines[cursor])
            ):
                # A PDF choice may wrap across lines. Preserve it as a single
                # choice instead of treating the continuation as another question.
                evidence_lines.append(lines[cursor])
                options[-1] = f"{options[-1]} {lines[cursor]}"
                cursor += 1
            else:
                break
        answer, answer_lines, cursor = _consume_answer(lines, cursor)
        evidence_lines.extend(answer_lines)
        cards.append(_draft(chunk, question, _normalise_answer(answer, options), evidence_lines, options))
        index = cursor if cursor > index + 1 else index + 1
    return cards


def _consume_answer(lines: list[str], cursor: int) -> tuple[str, list[str], int]:
    if cursor >= len(lines) or not (answer_match := ANSWER_PREFIX.match(lines[cursor])):
        return "", [], cursor
    answer_parts = [answer_match.group(1).strip()]
    evidence_lines = [lines[cursor]]
    cursor += 1
    while cursor < len(lines):
        line = lines[cursor]
        if (
            QUESTION_PREFIX.match(line)
            or ANSWER_PREFIX.match(line)
            or OPTION_LINE.match(line)
            or line.endswith("?")
        ):
            break
        if not line.startswith("<!--"):
            answer_parts.append(line)
            evidence_lines.append(line)
        cursor += 1
    return " ".join(part for part in answer_parts if part), evidence_lines, cursor


def _normalise_answer(answer: str, options: list[str]) -> str:
    """Convert an answer key such as "C" or "C." to the actual option text."""
    if not answer or not options:
        return answer
    key = re.match(r"^([A-H])(?:[.)]|\s|$)", answer.strip(), re.I)
    if key:
        index = ord(key.group(1).upper()) - ord("A")
        if index < len(options):
            return options[index]
    return answer


def _draft(
    chunk: DocumentChunk,
    question: str,
    answer: str,
    evidence_lines: list[str],
    options: list[str] | None = None,
) -> DraftFlashcard:
    evidence = "\n".join(evidence_lines)
    matching_source = f"{chunk.section_title}\n{chunk.text}"
    card = DraftFlashcard(
        question=question,
        answer=answer,
        evidence=evidence,
        page_number=chunk.page_start,
        section_title=chunk.section_title,
        chunk_id=chunk.id,
        requires_input=not bool(answer),
        evidence_match_quality=evidence_match_quality(evidence, matching_source),
        options=options or [],
    )
    card.confidence = calculate_confidence(card)
    return card


def _has_answer_nearby(lines: list[str], index: int) -> bool:
    return any(ANSWER_PREFIX.match(line) for line in lines[index + 1 : index + 4])
