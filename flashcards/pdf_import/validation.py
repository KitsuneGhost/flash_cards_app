"""Schema and semantic validation for generated draft cards."""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from .confidence import VAGUE_QUESTION
from .evidence import answer_support_quality, evidence_match_quality
from .models import DocumentChunk, DraftFlashcard
from .normalization import normalize_for_matching

TRIVIAL_METADATA_QUESTION = re.compile(
    r"\b(?:who (?:is|was) (?:the )?(?:professor|presenter|speaker|lecturer)|"
    r"what (?:is|was) (?:the )?(?:professor|presenter|speaker|lecturer)(?:'s)? name|"
    r"who (?:gave|delivered|made|wrote|authored|created|prepared|presented) (?:this|the) "
    r"(?:document|lecture|presentation|slide|source|text|file))\b",
    re.IGNORECASE,
)
SOURCE_DEPENDENT_QUESTION = re.compile(
    r"\b(?:according to|based on|as (?:stated|shown|described|mentioned) in) "
    r"(?:(?:this|the|provided|supplied) )?"
    r"(?:source(?: text)?|document|text|passage|presentation|slide|file|information|material|content)\b|"
    r"\b(?:this|the) (?:source(?: text)?|document|passage|presentation|slide|file) "
    r"(?:states?|shows?|describes?|mentions?|says?)\b",
    re.IGNORECASE,
)
VAGUE_RELATION_QUESTION = re.compile(
    r"^(?:how|in what way) (?:is|are|does|do) .{1,100} "
    r"(?:linked|related|connected|associated|involved) (?:to|with|in) .+\??$",
    re.IGNORECASE,
)
GENERIC_RELATION_ANSWER = re.compile(
    r"\b(?:is|are) (?:involved in|associated with|linked to|related to|important (?:for|in))\b|"
    r"\bplays? (?:an? )?(?:important |key )?role in\b",
    re.IGNORECASE,
)


class GeneratedCardPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    question: str = Field(min_length=3, max_length=500)
    answer: str = Field(min_length=1, max_length=1500)
    evidence: str = Field(min_length=3, max_length=3000)

    @field_validator("question", "answer", "evidence")
    @classmethod
    def reject_blank_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value.strip()


class GeneratedCardsPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cards: list[GeneratedCardPayload]


class MalformedModelOutput(ValueError):
    pass


def generated_cards_schema() -> dict[str, Any]:
    schema = GeneratedCardsPayload.model_json_schema()
    # Ollama's grammar compiler does not support JSON Schema string-length
    # keywords in every backend. Pydantic still enforces these limits when the
    # response is parsed, so omit them from the generation grammar only.
    _remove_string_length_keywords(schema)
    return schema


def _remove_string_length_keywords(value: Any) -> None:
    if isinstance(value, dict):
        value.pop("minLength", None)
        value.pop("maxLength", None)
        for child in value.values():
            _remove_string_length_keywords(child)
    elif isinstance(value, list):
        for child in value:
            _remove_string_length_keywords(child)


def parse_model_output(raw: str) -> list[GeneratedCardPayload]:
    try:
        return GeneratedCardsPayload.model_validate_json(raw).cards
    except (ValidationError, json.JSONDecodeError) as error:
        raise MalformedModelOutput("Ollama returned malformed or incomplete flashcard JSON.") from error


def validate_generated_card(payload: GeneratedCardPayload, chunk: DocumentChunk) -> DraftFlashcard | None:
    if normalize_for_matching(payload.question) == normalize_for_matching(payload.answer):
        return None
    if (
        len(payload.answer.split()) > 200
        or VAGUE_QUESTION.match(payload.question)
        or TRIVIAL_METADATA_QUESTION.search(payload.question)
        or SOURCE_DEPENDENT_QUESTION.search(payload.question)
        or VAGUE_RELATION_QUESTION.match(payload.question)
        or (len(payload.answer.split()) < 16 and GENERIC_RELATION_ANSWER.search(payload.answer))
    ):
        return None
    match_quality = evidence_match_quality(payload.evidence, chunk.text)
    if match_quality < 0.72:
        return None
    support = answer_support_quality(payload.answer, payload.evidence)
    if support < 0.25:
        return None
    warnings = []
    if match_quality < 0.9:
        warnings.append("Evidence was matched fuzzily to the source.")
    if support < 0.5:
        warnings.append("The answer has weak token-level support in the evidence.")
    return DraftFlashcard(
        question=payload.question,
        answer=payload.answer,
        evidence=payload.evidence,
        page_number=chunk.page_start,
        section_title=chunk.section_title,
        chunk_id=chunk.id,
        evidence_match_quality=match_quality,
        validation_warnings=warnings,
    )
