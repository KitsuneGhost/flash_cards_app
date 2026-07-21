"""Docling adapter that maps its document model into application types."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from .models import Document, DocumentBlock, Section, SourceLocation
from .normalization import normalize_document_text


class PdfParsingError(RuntimeError):
    """Safe parser failure suitable for showing to an end user."""


class DoclingPdfParser:
    def __init__(self, max_pages: int, max_file_size: int, enable_ocr: bool = True) -> None:
        self.max_pages = max_pages
        self.max_file_size = max_file_size
        self.enable_ocr = enable_ocr

    def parse(self, path: Path) -> Document:
        try:
            from docling.datamodel.base_models import InputFormat
            from docling.datamodel.pipeline_options import PdfPipelineOptions
            from docling.document_converter import DocumentConverter, PdfFormatOption
        except ImportError as error:
            raise PdfParsingError(
                "Docling is not installed. Install the project requirements first."
            ) from error

        try:
            options = PdfPipelineOptions(do_ocr=self.enable_ocr, do_table_structure=True)
            converter = DocumentConverter(
                allowed_formats=[InputFormat.PDF],
                format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=options)},
            )
            result = converter.convert(
                path, raises_on_error=True, max_num_pages=self.max_pages, max_file_size=self.max_file_size
            )
            return self._to_document(result.document, path)
        except PdfParsingError:
            raise
        except Exception as error:
            message = str(error).lower()
            if "password" in message or "encrypted" in message:
                safe_message = "Encrypted PDFs are not supported. Remove the password and try again."
            elif "page" in message and ("limit" in message or "maximum" in message):
                safe_message = f"The PDF exceeds the {self.max_pages}-page limit."
            else:
                safe_message = "Docling could not read this PDF. It may be malformed or unsupported."
            raise PdfParsingError(safe_message) from error

    def _to_document(self, source: Any, path: Path) -> Document:
        identifier = hashlib.sha256(path.read_bytes()).hexdigest()[:24]
        sections = [Section(title="Document", level=0)]
        title = ""
        page_numbers: set[int] = set()
        heading_stack: dict[int, str] = {}

        for item, hierarchy_level in source.iterate_items():
            text = self._item_text(item, source)
            if not text:
                continue
            label = str(getattr(item, "label", "")).lower()
            page_start, page_end = self._pages(item)
            if page_start:
                page_numbers.update(range(page_start, (page_end or page_start) + 1))
            location = SourceLocation(page_start, page_end)
            if "section_header" in label or label.endswith("title"):
                level = max(1, int(getattr(item, "level", hierarchy_level or 1)))
                if not title:
                    title = text
                heading_stack = {key: value for key, value in heading_stack.items() if key < level}
                heading_stack[level] = text
                parent_level = max((key for key in heading_stack if key < level), default=level)
                parent_title = heading_stack[parent_level]
                sections.append(
                    Section(
                        title=parent_title,
                        level=level,
                        subsection_title=text if parent_title != text else "",
                    )
                )
                continue
            kind = "table" if "table" in label else "list" if "list" in label else "paragraph"
            sections[-1].blocks.append(
                DocumentBlock(text=text, kind=kind, level=hierarchy_level, location=location)
            )

        sections = [section for section in sections if section.blocks]
        if not sections:
            raise PdfParsingError("No readable text was found in the PDF.")
        document_name = getattr(source, "name", None) or path.stem
        return Document(
            identifier=identifier,
            title=title or str(document_name),
            sections=sections,
            page_count=max(page_numbers, default=len(getattr(source, "pages", {}))),
            metadata={"source_name": path.name},
        )

    @staticmethod
    def _item_text(item: Any, document: Any) -> str:
        text = getattr(item, "text", "") or ""
        if not text and hasattr(item, "export_to_markdown"):
            try:
                text = item.export_to_markdown(doc=document)
            except (TypeError, ValueError):
                text = ""
        return normalize_document_text(str(text))

    @staticmethod
    def _pages(item: Any) -> tuple[int | None, int | None]:
        pages = []
        for provenance in getattr(item, "prov", []) or []:
            page = getattr(provenance, "page_no", None)
            if isinstance(page, int):
                pages.append(page)
        return (min(pages), max(pages)) if pages else (None, None)
