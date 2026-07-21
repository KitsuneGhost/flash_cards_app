"""Heading-aware, block-preserving document chunking."""

from __future__ import annotations

import re

from .models import Document, DocumentBlock, DocumentChunk, Section


def _word_count(value: str) -> int:
    return len(value.split())


def _split_large_block(block: DocumentBlock, target_words: int) -> list[DocumentBlock]:
    if _word_count(block.text) <= target_words:
        return [block]
    sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9])", block.text)
    pieces: list[str] = []
    current: list[str] = []
    for sentence in sentences:
        words = sentence.split()
        if len(words) > target_words:
            if current:
                pieces.append(" ".join(current))
                current = []
            pieces.extend(" ".join(words[i : i + target_words]) for i in range(0, len(words), target_words))
        elif current and len(current) + len(words) > target_words:
            pieces.append(" ".join(current))
            current = words
        else:
            current.extend(words)
    if current:
        pieces.append(" ".join(current))
    return [
        DocumentBlock(text=piece, kind=block.kind, level=block.level, location=block.location)
        for piece in pieces
    ]


def _overlap_text(blocks: list[DocumentBlock], overlap_words: int) -> str:
    if overlap_words <= 0:
        return ""
    words = "\n".join(block.text for block in blocks).split()
    return " ".join(words[-overlap_words:])


def chunk_document(document: Document, target_words: int, overlap_words: int) -> list[DocumentChunk]:
    if target_words < 1 or overlap_words < 0 or overlap_words >= target_words:
        raise ValueError("Chunk sizes must be positive and overlap must be smaller than the target.")
    chunks: list[DocumentChunk] = []
    previous_context = ""
    for section in document.sections:
        expanded = [piece for block in section.blocks for piece in _split_large_block(block, target_words)]
        current: list[DocumentBlock] = []
        current_words = 0
        for block in expanded:
            block_words = _word_count(block.text)
            if current and current_words + block_words > target_words:
                _append_chunk(chunks, document, section, current, previous_context)
                previous_context = _overlap_text(current, overlap_words)
                current, current_words = [], 0
            current.append(block)
            current_words += block_words
        if current:
            _append_chunk(chunks, document, section, current, previous_context)
            previous_context = _overlap_text(current, overlap_words)
    return chunks


def _append_chunk(
    chunks: list[DocumentChunk],
    document: Document,
    section: Section,
    blocks: list[DocumentBlock],
    context_before: str,
) -> None:
    pages = [
        page for block in blocks for page in (block.location.page_start, block.location.page_end) if page
    ]
    index = len(chunks)
    text = "\n\n".join(block.text for block in blocks)
    chunks.append(
        DocumentChunk(
            id=f"{document.identifier}-{index}",
            document_id=document.identifier,
            index=index,
            section_title=section.title,
            subsection_title=section.subsection_title,
            text=text,
            page_start=min(pages) if pages else None,
            page_end=max(pages) if pages else None,
            context_before=context_before,
        )
    )
