"""Framework-independent types shared by the PDF import pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

BlockKind = Literal["heading", "paragraph", "list", "table", "question", "other"]


@dataclass(frozen=True)
class SourceLocation:
    page_start: int | None = None
    page_end: int | None = None


@dataclass(frozen=True)
class DocumentBlock:
    text: str
    kind: BlockKind = "paragraph"
    level: int = 0
    location: SourceLocation = field(default_factory=SourceLocation)


@dataclass
class Section:
    title: str
    level: int
    blocks: list[DocumentBlock] = field(default_factory=list)
    subsection_title: str = ""


@dataclass
class Document:
    identifier: str
    title: str
    sections: list[Section]
    page_count: int
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class DocumentChunk:
    id: str
    document_id: str
    index: int
    section_title: str
    subsection_title: str
    text: str
    page_start: int | None
    page_end: int | None
    context_before: str = ""


@dataclass
class DraftFlashcard:
    question: str
    answer: str
    evidence: str
    page_number: int | None
    section_title: str
    chunk_id: str
    confidence: float = 0.0
    requires_input: bool = False
    evidence_match_quality: float = 0.0
    validation_warnings: list[str] = field(default_factory=list)
    options: list[str] = field(default_factory=list)
