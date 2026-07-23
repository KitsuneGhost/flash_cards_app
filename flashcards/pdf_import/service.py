"""Bounded in-process orchestration for PDF import jobs."""

from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import repository
from .chunking import chunk_document, extraction_chunks
from .confidence import calculate_confidence
from .duplicates import remove_duplicates
from .generation import generate_cards
from .models import DraftFlashcard
from .ollama import OllamaClient, OllamaError
from .parser import DoclingPdfParser, PdfParsingError
from .question_extraction import extract_questions

LOGGER = logging.getLogger(__name__)


class PdfImportManager:
    def __init__(
        self,
        parser: DoclingPdfParser,
        ollama: OllamaClient,
        worker_count: int,
        target_words: int,
        overlap_words: int,
        max_chunks: int,
        max_cards_per_chunk: int,
        max_generated_cards: int,
    ) -> None:
        self.parser = parser
        self.ollama = ollama
        self.target_words = target_words
        self.overlap_words = overlap_words
        self.max_chunks = max_chunks
        self.max_cards_per_chunk = max_cards_per_chunk
        self.max_generated_cards = max_generated_cards
        self.executor = ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix="pdf-import")

    def submit(self, job_id: str, user_id: int, mode: str, path: Path) -> None:
        self.executor.submit(self._process, job_id, user_id, mode, path)

    def _process(self, job_id: str, user_id: int, mode: str, path: Path) -> None:
        warnings: list[str] = []
        try:
            repository.update_job(job_id, status="parsing", progress=10)
            # Existing-question extraction can use a PDF's native text layer directly.
            # This avoids loading Docling/OCR for the common exam-PDF case.
            document = self.parser.parse(path, prefer_native_questions=mode == "extract")
            self._cancel_if_requested(job_id)
            repository.update_job(job_id, status="chunking", progress=25, document_title=document.title)
            chunks = (
                extraction_chunks(document)
                if mode == "extract"
                else chunk_document(document, self.target_words, self.overlap_words)
            )
            if mode == "generate" and len(chunks) > self.max_chunks:
                chunks = chunks[: self.max_chunks]
                warnings.append(f"Only the first {self.max_chunks} chunks were processed.")
            repository.update_job(job_id, status="generating", progress=35, total_chunks=len(chunks))

            cards: list[DraftFlashcard] = []
            for index, chunk in enumerate(chunks):
                self._cancel_if_requested(job_id)
                try:
                    if mode == "extract":
                        cards.extend(extract_questions(chunk))
                    else:
                        generated, chunk_warnings = generate_cards(
                            chunk, self.ollama.generate, self.max_cards_per_chunk
                        )
                        cards.extend(generated)
                        warnings.extend(chunk_warnings)
                except (OllamaError, ValueError) as error:
                    LOGGER.warning("PDF job %s chunk %s failed: %s", job_id, chunk.id, error)
                    warnings.append(f"Chunk {index + 1} failed: {error}")
                progress = 35 + round(45 * (index + 1) / max(1, len(chunks)))
                repository.update_job(job_id, progress=progress, processed_chunks=index + 1)
                if mode == "generate" and len(cards) >= self.max_generated_cards:
                    cards = cards[: self.max_generated_cards]
                    warnings.append(f"Stopped at the {self.max_generated_cards}-card document limit.")
                    break

            repository.update_job(job_id, status="validating", progress=85)
            cards = remove_duplicates(cards)
            for card in cards:
                card.confidence = calculate_confidence(card)
            repository.save_drafts(job_id, user_id, cards)
            if mode == "generate" and not cards:
                raise RuntimeError("No valid cards were generated. Check Ollama and the source content.")
            status = "partially_completed" if warnings else "completed"
            repository.update_job(
                job_id,
                status=status,
                progress=100,
                warnings_json=json.dumps(warnings),
                completed_at=repository.now_iso(),
            )
        except _Cancelled:
            repository.update_job(job_id, status="cancelled", progress=100, completed_at=repository.now_iso())
        except (PdfParsingError, RuntimeError) as error:
            LOGGER.warning("PDF job %s failed: %s", job_id, error)
            repository.update_job(
                job_id,
                status="failed",
                progress=100,
                error_message=str(error),
                warnings_json=json.dumps(warnings),
                completed_at=repository.now_iso(),
            )
        except Exception:
            LOGGER.exception("Unexpected failure in PDF job %s", job_id)
            repository.update_job(
                job_id,
                status="failed",
                progress=100,
                error_message="PDF processing failed unexpectedly. Check the server log for details.",
                warnings_json=json.dumps(warnings),
                completed_at=repository.now_iso(),
            )
        finally:
            path.unlink(missing_ok=True)

    @staticmethod
    def _cancel_if_requested(job_id: str) -> None:
        if repository.cancellation_requested(job_id):
            raise _Cancelled


class _Cancelled(Exception):
    pass
