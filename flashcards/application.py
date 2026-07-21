"""Application composition and server startup."""

from http.server import ThreadingHTTPServer

from .config import (
    HOST,
    OLLAMA_BASE_URL,
    OLLAMA_MAX_RETRIES,
    OLLAMA_MODEL,
    OLLAMA_TEMPERATURE,
    OLLAMA_TIMEOUT_SECONDS,
    PDF_CHUNK_OVERLAP_WORDS,
    PDF_CHUNK_TARGET_WORDS,
    PDF_MAX_CARDS_PER_CHUNK,
    PDF_MAX_CHUNKS,
    PDF_MAX_GENERATED_CARDS,
    PDF_MAX_PAGES,
    PDF_MAX_SIZE_BYTES,
    PDF_WORKER_COUNT,
    PORT,
)
from .database import init_db
from .pdf_import.ollama import OllamaClient
from .pdf_import.parser import DoclingPdfParser
from .pdf_import.repository import recover_interrupted_jobs
from .pdf_import.service import PdfImportManager
from .web import create_handler


def main() -> None:
    init_db()
    recover_interrupted_jobs()
    manager = PdfImportManager(
        parser=DoclingPdfParser(PDF_MAX_PAGES, PDF_MAX_SIZE_BYTES),
        ollama=OllamaClient(
            OLLAMA_BASE_URL, OLLAMA_MODEL, OLLAMA_TIMEOUT_SECONDS, OLLAMA_MAX_RETRIES, OLLAMA_TEMPERATURE
        ),
        worker_count=PDF_WORKER_COUNT,
        target_words=PDF_CHUNK_TARGET_WORDS,
        overlap_words=PDF_CHUNK_OVERLAP_WORDS,
        max_chunks=PDF_MAX_CHUNKS,
        max_cards_per_chunk=PDF_MAX_CARDS_PER_CHUNK,
        max_generated_cards=PDF_MAX_GENERATED_CARDS,
    )
    server = ThreadingHTTPServer((HOST, PORT), create_handler(manager))
    print(f"Flash Cards running at http://{HOST}:{PORT}")
    print("Create an account at /register, then log in to import and study decks.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        manager.executor.shutdown(wait=False, cancel_futures=True)
