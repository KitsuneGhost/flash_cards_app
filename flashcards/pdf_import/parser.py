"""Docling adapter that maps its document model into application types."""

from __future__ import annotations

import hashlib
import re
import tempfile
from pathlib import Path
from typing import Any

from .models import Document, DocumentBlock, Section, SourceLocation
from .normalization import normalize_document_text

OPTION_LINE = re.compile(r"^\s*[A-H][.)]\s+(?P<text>.+)", re.I)
QUESTION_LINE = re.compile(r"^(?:Q(?:uestion)?\s*[:.)-]\s*|\d{1,3}[.)]\s+).+\?$", re.I)


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
            preview_path = self._preview_pdf(path)
            try:
                result = converter.convert(
                    preview_path or path,
                    raises_on_error=True,
                    max_num_pages=self.max_pages,
                    max_file_size=self.max_file_size,
                )
            finally:
                if preview_path:
                    preview_path.unlink(missing_ok=True)
            highlighted_options = self._highlighted_options(path)
            document = self._to_document(result.document, path, highlighted_options)
            self._append_raw_question_pages(document, path, highlighted_options)
            return document
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

    def _preview_pdf(self, path: Path) -> Path | None:
        """Return a temporary first-pages PDF for quick local preview imports."""
        try:
            import pypdfium2 as pdfium

            source = pdfium.PdfDocument(path)
            if len(source) <= self.max_pages:
                source.close()
                return None
            preview = pdfium.PdfDocument.new()
            preview.import_pages(source, list(range(self.max_pages)))
            with tempfile.NamedTemporaryFile(
                prefix="flashcards-preview-", suffix=".pdf", delete=False
            ) as file:
                preview_path = Path(file.name)
            preview.save(preview_path)
            preview.close()
            source.close()
            return preview_path
        except Exception:
            # Let Docling process the original file if PDFium cannot build a preview.
            return None

    def _to_document(
        self, source: Any, path: Path, highlighted_options: dict[int, set[str]] | None = None
    ) -> Document:
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
            if page_start and highlighted_options:
                text = self._mark_highlighted_answers(text, highlighted_options.get(page_start, set()))
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
    def _mark_highlighted_answers(text: str, highlighted_options: set[str]) -> str:
        """Add an answer key after its complete highlighted choice group."""
        if not highlighted_options:
            return text
        lines: list[str] = []
        pending_answer = ""
        option_count = 0
        source_lines = text.splitlines()
        for index, line in enumerate(source_lines):
            lines.append(line)
            match = OPTION_LINE.match(line)
            if match:
                option_count += 1
                if normalize_document_text(match.group("text")).casefold() in highlighted_options:
                    pending_answer = match.group("text").strip()
            if pending_answer and (
                not match or index + 1 == len(source_lines) or not OPTION_LINE.match(source_lines[index + 1])
            ):
                # Do not put Answer: between B and C: the extraction code correctly
                # sees a consecutive A–E block only when the key comes afterwards.
                if option_count >= 2:
                    lines.append(f"Answer: {pending_answer}")
                pending_answer = ""
                option_count = 0
            elif not match:
                option_count = 0
        return "\n".join(lines)

    def _highlighted_options(self, path: Path) -> dict[int, set[str]]:
        """Read highlighted text directly from a PDF page when available.

        Previous exams often encode the answer as a coloured rectangle behind the
        choice rather than an answer-key string. Docling preserves the text but not
        that paint information, so PDFium supplies this small visual supplement.
        """
        try:
            import pypdfium2 as pdfium
        except ImportError:
            return {}
        matches: dict[int, set[str]] = {}
        try:
            pdf = pdfium.PdfDocument(path)
            for page_number in range(min(len(pdf), self.max_pages)):
                page = pdf.get_page(page_number)
                text_page = page.get_textpage()
                native_text = normalize_document_text(text_page.get_text_range())
                native_lines = native_text.splitlines()
                if sum(bool(OPTION_LINE.match(line)) for line in native_lines) < 2 or not any(
                    QUESTION_LINE.match(line) for line in native_lines
                ):
                    text_page.close()
                    page.close()
                    continue
                image = page.render(scale=1.5).to_pil().convert("RGB")
                line_chars: list[tuple[str, tuple[float, float, float, float]]] = []
                for index, character in enumerate(text_page.get_text_range()):
                    if character in "\r\n":
                        PdfHighlightDetector._collect(line_chars, image, page, matches, page_number + 1)
                        line_chars = []
                    else:
                        line_chars.append((character, text_page.get_charbox(index)))
                PdfHighlightDetector._collect(line_chars, image, page, matches, page_number + 1)
                text_page.close()
                page.close()
            pdf.close()
        except Exception:
            # Colour detection is an enhancement; normal text extraction remains usable.
            return {}
        return matches

    def _append_raw_question_pages(
        self, document: Document, path: Path, highlighted_options: dict[int, set[str]]
    ) -> None:
        """Recover complete question/choice groups from the PDF's native text order."""
        try:
            import pypdfium2 as pdfium

            pdf = pdfium.PdfDocument(path)
            raw_sections: list[Section] = []
            for page_index in range(min(len(pdf), self.max_pages)):
                page = pdf.get_page(page_index)
                text_page = page.get_textpage()
                text = normalize_document_text(text_page.get_text_range())
                text_page.close()
                page.close()
                lines = text.splitlines()
                if sum(bool(OPTION_LINE.match(line)) for line in lines) < 2 or not any(
                    QUESTION_LINE.match(line) for line in lines
                ):
                    continue
                page_number = page_index + 1
                raw_sections.append(
                    Section(
                        title=f"PDF page {page_number}",
                        level=0,
                        blocks=[
                            DocumentBlock(
                                text=self._mark_highlighted_answers(
                                    text, highlighted_options.get(page_number, set())
                                ),
                                kind="list",
                                location=SourceLocation(page_number, page_number),
                            )
                        ],
                    )
                )
            pdf.close()
            # Put the native page representation first: the importer's bounded
            # chunk limit must not discard this question/choice recovery path
            # after processing only Docling's layout fragments.
            document.sections[:0] = raw_sections
        except Exception:
            # Docling extraction remains available when a PDF has no native text layer.
            return

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


class PdfHighlightDetector:
    @staticmethod
    def _collect(
        chars: list[tuple[str, tuple[float, float, float, float]]],
        image: Any,
        page: Any,
        matches: dict[int, set[str]],
        page_number: int,
    ) -> None:
        text = "".join(character for character, _ in chars).strip()
        if not OPTION_LINE.match(text) or not chars:
            return
        left = min(box[0] for _, box in chars)
        bottom = min(box[1] for _, box in chars)
        right = max(box[2] for _, box in chars)
        top = max(box[3] for _, box in chars)
        scale_x = image.width / page.get_width()
        scale_y = image.height / page.get_height()
        crop = image.crop(
            (
                max(0, int(left * scale_x) - 3),
                max(0, int((page.get_height() - top) * scale_y) - 3),
                min(image.width, int(right * scale_x) + 3),
                min(image.height, int((page.get_height() - bottom) * scale_y) + 3),
            )
        )
        pixels = list(crop.getdata())
        # Highlighter fills are normally light but noticeably coloured: yellow,
        # green, cyan, blue, orange, or pink. Requiring both brightness and a
        # channel spread excludes white/grey paper and most black text.
        highlighted = sum(
            max(red, green, blue) > 150 and max(red, green, blue) - min(red, green, blue) > 45
            for red, green, blue in pixels
        )
        if pixels and highlighted / len(pixels) > 0.12:
            matches.setdefault(page_number, set()).add(
                normalize_document_text(OPTION_LINE.match(text).group("text")).casefold()
            )
