# Flash Cards App

A local, dependency-light web app for importing Anki packages or creating reviewable flashcards from PDFs.
PDF parsing uses Docling and optional card generation uses a local Ollama model. Uploaded PDFs and source
text are not sent to paid or hosted inference APIs.

## Architecture

```text
app.py                         development entry point
flashcards/
  application.py              server and worker composition
  config.py                   environment-driven settings
  database.py                 SQLite schema lifecycle
  auth.py                     users, password hashing, sessions
  decks.py                    decks and study progress
  importer.py                 Anki package import
  views.py                    server-rendered HTML
  web.py                      routes, request parsing, responses
  pdf_import/
    models.py                 structured document and draft types
    upload.py                 PDF validation and temporary files
    parser.py                 Docling adapter
    normalization.py          text and evidence normalization
    chunking.py               heading-aware bounded chunks
    question_extraction.py    deterministic question extraction
    ollama.py                 local Ollama HTTP client
    generation.py             grounded prompt and generation flow
    validation.py             Pydantic schema and quality gate
    evidence.py               exact and fuzzy evidence verification
    duplicates.py             document-wide duplicate detection
    confidence.py             transparent quality score
    repository.py             jobs, drafts, and approval persistence
    service.py                bounded background orchestration
static/
  study.js                    study interaction
  pdf_import.js               upload, polling, review, and approval
  styles.css                  shared styles
tests/                        unit and isolated SQLite tests
```

The HTTP backend remains Python's standard-library `ThreadingHTTPServer`. PDF work runs in a bounded
in-process thread pool. Job state and draft cards are stored in SQLite, but PDF files are random-named
temporary files deleted in the worker's `finally` block. Generated cards are never inserted into a deck
until the user explicitly selects and saves them.

## Install

Docling and its local ML dependencies are substantial. A Python 3.10+ virtual environment is required;
Python 3.12 is a conservative choice if the newest system Python is not supported by a transitive ML package.

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Docling downloads its parsing models locally on first use. For an offline machine, prefetch the models as
described by Docling and set `DOCLING_ARTIFACTS_PATH` before starting the app. OCR is enabled by default.

Install Ollama from https://ollama.com, then download and start the default local instruction model:

```bash
ollama pull qwen3:4b
ollama serve
```

Ollama normally serves its local API at `http://localhost:11434`. Deterministic extraction mode does not
require Ollama.

## Configure

The application reads environment variables directly; it does not automatically load `.env` files. Example
values are in `.env.example`. Export values in your shell or use your process manager.

| Variable | Default | Purpose |
|---|---:|---|
| `FLASHCARDS_HOST` | `127.0.0.1` | HTTP bind address |
| `FLASHCARDS_PORT` | `8000` | HTTP port |
| `FLASHCARDS_DB_PATH` | `data/flashcards.sqlite3` | SQLite database path |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Local Ollama server |
| `OLLAMA_MODEL` | `qwen3:4b` | Local model name |
| `OLLAMA_TIMEOUT_SECONDS` | `120` | Per-request timeout |
| `OLLAMA_MAX_RETRIES` | `2` | Transient retry count |
| `OLLAMA_TEMPERATURE` | `0.1` | Generation temperature |
| `PDF_MAX_SIZE_MB` | `50` | Upload limit |
| `PDF_MAX_PAGES` | `500` | Docling page limit |
| `PDF_CHUNK_TARGET_WORDS` | `1500` | Approximate chunk size |
| `PDF_CHUNK_OVERLAP_WORDS` | `100` | Previous-chunk context |
| `PDF_MAX_CARDS_PER_CHUNK` | `10` | Per-chunk output cap |
| `PDF_MAX_CHUNKS` | `100` | Per-document chunk cap |
| `PDF_MAX_GENERATED_CARDS` | `500` | Per-document card cap |
| `PDF_MAX_CONCURRENT_JOBS_PER_USER` | `1` | Expensive-job limit |
| `PDF_WORKER_COUNT` | `2` | Process-local worker count |

## Run

```bash
source .venv/bin/activate
python app.py
```

Open http://127.0.0.1:8000/register. After login, choose **Create cards from a PDF** on the deck dashboard.

The PDF workflow is:

1. Upload a PDF and choose deterministic extraction or Ollama generation.
2. Poll the SQLite-backed job while Docling parses and the backend processes chunks.
3. Review and edit every draft with its evidence, page, section, and confidence indicator.
4. Select only wanted cards and save them into a new deck.

Extracted questions without an answer remain blank and cannot be approved until the user supplies an answer.

## Confidence score

Confidence is calculated by the backend, never accepted from Ollama. The score combines exact/fuzzy evidence
matching (42%), answer-token support (20%), question form and clarity, answer length, and source metadata.
Vague or suspicious medical/advice language and near-duplicate similarity reduce the result. Missing-answer
cards are capped at 55%. It is a review-priority indicator, not a guarantee of correctness.

## Test and lint

```bash
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
python -m pytest -q
ruff check .
ruff format --check .
```

Normal tests mock generation and do not contact Ollama or load Docling models. Optional local integration:

```bash
RUN_LOCAL_INTEGRATION=1 \
PDF_INTEGRATION_SAMPLE=/absolute/path/to/sample.pdf \
python -m pytest -m integration tests/integration/test_local_services.py
```

## Database changes

Startup performs idempotent schema upgrades in `flashcards/database.py`. It adds:

- `pdf_import_jobs` for ownership, status, progress, errors, warnings, and cancellation
- `generated_flashcard_drafts` for review-only cards
- source evidence, page, section, document, and generation-mode columns on approved cards

The source PDF is not retained. Draft metadata remains in SQLite so a completed review can survive a refresh.

## Current limitations

- Workers and cancellation are process-local. Restarting the server marks interrupted jobs failed; it does not
  resume them. Cancellation takes effect between parsing/chunks and cannot interrupt a running Docling or Ollama call.
- Running multiple application processes is not supported because each would own a separate worker pool.
- OCR quality, heading hierarchy, page attribution, and tables depend on Docling's interpretation of the PDF.
- Deterministic extraction intentionally favors precision and will miss unusual question layouts.
- Evidence support uses text normalization and fuzzy/token matching, not semantic entailment.
- Uploaded PDF bytes are held in the request body before being written to a temporary file.
- Existing application-wide protections such as CSRF tokens and general request rate limiting are not yet present.
- Draft rows are retained until their owning job or user is deleted; no automatic draft-retention purge exists yet.
