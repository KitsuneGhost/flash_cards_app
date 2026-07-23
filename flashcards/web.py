"""HTTP request parsing, routing, and responses."""

from __future__ import annotations

import json
import posixpath
import re
import sqlite3
import zipfile
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urlparse

from . import auth, decks, views
from .config import (
    MAX_UPLOAD_BYTES,
    PDF_MAX_CONCURRENT_JOBS_PER_USER,
    PDF_MAX_SIZE_BYTES,
    SESSION_COOKIE,
    SESSION_DAYS,
    STATIC_DIR,
)
from .importer import parse_apkg
from .pdf_import import repository as pdf_repository
from .pdf_import.service import PdfImportManager
from .pdf_import.upload import UploadValidationError, create_temporary_pdf, validate_pdf_upload


def parse_multipart(body: bytes, content_type: str) -> dict[str, tuple[str, bytes]]:
    match = re.search(r"boundary=(?P<boundary>[^;]+)", content_type)
    if not match:
        raise ValueError("Missing multipart boundary.")
    delimiter = b"--" + match.group("boundary").strip('"').encode()
    files: dict[str, tuple[str, bytes]] = {}
    for part in body.split(delimiter):
        part = part.strip()
        if not part or part == b"--":
            continue
        if part.endswith(b"--"):
            part = part[:-2].strip()
        header_blob, _, content = part.partition(b"\r\n\r\n")
        headers = header_blob.decode("utf-8", "replace").split("\r\n")
        disposition = next((h for h in headers if h.lower().startswith("content-disposition:")), "")
        name_match = re.search(r'name="([^"]+)"', disposition)
        filename_match = re.search(r'filename="([^"]*)"', disposition)
        if name_match and filename_match:
            files[name_match.group(1)] = (Path(filename_match.group(1)).name, content.removesuffix(b"\r\n"))
    return files


def parse_multipart_form(
    body: bytes,
    content_type: str,
) -> tuple[dict[str, str], dict[str, tuple[str, str, bytes]]]:
    match = re.search(r"boundary=(?P<boundary>[^;]+)", content_type)
    if not match:
        raise ValueError("Missing multipart boundary.")
    delimiter = b"--" + match.group("boundary").strip('"').encode()
    fields: dict[str, str] = {}
    files: dict[str, tuple[str, str, bytes]] = {}
    for raw_part in body.split(delimiter)[1:]:
        if raw_part.startswith(b"--"):
            break
        part = raw_part.removeprefix(b"\r\n").removesuffix(b"\r\n")
        header_blob, separator, content = part.partition(b"\r\n\r\n")
        if not separator:
            continue
        headers = header_blob.decode("utf-8", "replace").split("\r\n")
        disposition = next((line for line in headers if line.lower().startswith("content-disposition:")), "")
        name_match = re.search(r'name="([^"]+)"', disposition)
        if not name_match:
            continue
        name = name_match.group(1)
        filename_match = re.search(r'filename="([^"]*)"', disposition)
        if filename_match:
            part_type = next(
                (
                    line.split(":", 1)[1].strip()
                    for line in headers
                    if line.lower().startswith("content-type:")
                ),
                "application/octet-stream",
            )
            files[name] = (Path(filename_match.group(1)).name, part_type, content)
        else:
            fields[name] = content.decode("utf-8", "replace")
    return fields, files


class Handler(BaseHTTPRequestHandler):
    server_version = "FlashCards/0.1"
    pdf_manager: PdfImportManager | None = None

    def log_message(self, format: str, *args: Any) -> None:
        print(f"{self.address_string()} - {format % args}")

    def session_token(self) -> str | None:
        morsel = SimpleCookie(self.headers.get("Cookie", "")).get(SESSION_COOKIE)
        return morsel.value if morsel else None

    def current_user(self) -> sqlite3.Row | None:
        return auth.get_session_user(self.session_token())

    def require_user(self) -> sqlite3.Row | None:
        user = self.current_user()
        if not user:
            self.redirect(f"/login?next={quote(self.path)}")
        return user

    def send_html(self, body: bytes, status: HTTPStatus = HTTPStatus.OK) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def redirect(self, path: str) -> None:
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", path)
        self.end_headers()

    def redirect_with_cookie(self, path: str, token: str | None = None, clear: bool = False) -> None:
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", path)
        if token:
            self.send_header(
                "Set-Cookie",
                f"{SESSION_COOKIE}={token}; HttpOnly; SameSite=Lax; Path=/; Max-Age={SESSION_DAYS * 86400}",
            )
        if clear:
            self.send_header("Set-Cookie", f"{SESSION_COOKIE}=; HttpOnly; SameSite=Lax; Path=/; Max-Age=0")
        self.end_headers()

    def read_form(self) -> dict[str, str]:
        length = int(self.headers.get("Content-Length", "0"))
        parsed = parse_qs(self.rfile.read(length).decode("utf-8", "replace"), keep_blank_values=True)
        return {key: values[0] for key, values in parsed.items()}

    def read_json(self, max_bytes: int = 1024 * 1024) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > max_bytes:
            raise ValueError("Invalid JSON request size.")
        payload = json.loads(self.rfile.read(length))
        if not isinstance(payload, dict):
            raise ValueError("JSON body must be an object.")
        return payload

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        try:
            if parsed.path.startswith("/static/"):
                self.serve_static(parsed.path)
            elif parsed.path == "/login":
                if self.current_user():
                    return self.redirect("/")
                query = parse_qs(parsed.query)
                self.send_html(
                    views.render_auth_page(
                        "login", query.get("message", [""])[0], query.get("next", ["/"])[0]
                    )
                )
            elif parsed.path == "/register":
                if self.current_user():
                    return self.redirect("/")
                self.send_html(
                    views.render_auth_page("register", parse_qs(parsed.query).get("message", [""])[0])
                )
            elif parsed.path == "/":
                if user := self.require_user():
                    message = parse_qs(parsed.query).get("message", [""])[0]
                    self.send_html(views.render_dashboard(user, decks.list_decks(user["id"]), message))
            elif parsed.path == "/pdf-import":
                if user := self.require_user():
                    self.send_html(views.render_pdf_import(user))
            elif match := re.fullmatch(r"/api/pdf-imports/([a-f0-9]{32})(?:/drafts)?", parsed.path):
                if user := self.require_user():
                    self.handle_pdf_job_get(user, match.group(1), parsed.path.endswith("/drafts"))
            elif parsed.path.startswith("/deck/"):
                if user := self.require_user():
                    deck_id = int(parsed.path.removeprefix("/deck/").strip("/"))
                    deck, cards = decks.get_deck_for_study(user["id"], deck_id)
                    self.send_html(
                        views.render_exam(user, deck, cards)
                        if deck["kind"] == "mock_exam"
                        else views.render_study(user, deck, cards)
                    )
            else:
                self.send_error(HTTPStatus.NOT_FOUND)
        except (LookupError, ValueError):
            self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path == "/register":
            self.handle_register()
        elif path == "/login":
            self.handle_login()
        elif path == "/logout":
            auth.delete_session(self.session_token())
            self.redirect_with_cookie("/login", clear=True)
        elif path == "/upload":
            if user := self.require_user():
                self.handle_upload(user)
        elif path == "/api/progress":
            if user := self.require_user():
                self.handle_progress(user)
        elif match := re.fullmatch(r"/api/decks/(\d+)/exam-submit", path):
            if user := self.require_user():
                self.handle_exam_submit(user, int(match.group(1)))
        elif path == "/api/pdf-imports":
            if user := self.require_user():
                self.handle_pdf_create(user)
        elif match := re.fullmatch(r"/api/pdf-imports/([a-f0-9]{32})/(cancel|approve)", path):
            if user := self.require_user():
                if match.group(2) == "cancel":
                    self.handle_pdf_cancel(user, match.group(1))
                else:
                    self.handle_pdf_approve(user, match.group(1))
        else:
            self.send_error(HTTPStatus.NOT_FOUND)

    def do_PATCH(self) -> None:
        match = re.fullmatch(r"/api/pdf-imports/([a-f0-9]{32})/drafts/(\d+)", urlparse(self.path).path)
        user = self.require_user()
        if not match or not user:
            if not match:
                self.send_error(HTTPStatus.NOT_FOUND)
            return
        try:
            updated = pdf_repository.update_draft(
                user["id"], match.group(1), int(match.group(2)), self.read_json()
            )
            self.send_json({"ok": updated}, HTTPStatus.OK if updated else HTTPStatus.NOT_FOUND)
        except (ValueError, json.JSONDecodeError) as error:
            self.send_json({"ok": False, "error": str(error)}, HTTPStatus.BAD_REQUEST)

    def do_DELETE(self) -> None:
        match = re.fullmatch(r"/api/pdf-imports/([a-f0-9]{32})/drafts/(\d+)", urlparse(self.path).path)
        user = self.require_user()
        if not match or not user:
            if not match:
                self.send_error(HTTPStatus.NOT_FOUND)
            return
        deleted = pdf_repository.delete_draft(user["id"], match.group(1), int(match.group(2)))
        self.send_json({"ok": deleted}, HTTPStatus.OK if deleted else HTTPStatus.NOT_FOUND)

    def handle_register(self) -> None:
        form = self.read_form()
        try:
            user_id = auth.create_user(form.get("username", ""), form.get("password", ""))
        except ValueError as error:
            return self.redirect(f"/register?message={quote(str(error))}")
        self.redirect_with_cookie("/", token=auth.create_session(user_id))

    def handle_login(self) -> None:
        form = self.read_form()
        user = auth.authenticate_user(form.get("username", ""), form.get("password", ""))
        if not user:
            return self.redirect("/login?message=Invalid%20username%20or%20password.")
        next_path = form.get("next") or "/"
        if not next_path.startswith("/") or next_path.startswith("//"):
            next_path = "/"
        self.redirect_with_cookie(next_path, token=auth.create_session(user["id"]))

    def handle_upload(self, user: sqlite3.Row) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > MAX_UPLOAD_BYTES:
            return self.send_error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "Upload must be under 100 MB.")
        try:
            filename, content = parse_multipart(
                self.rfile.read(length), self.headers.get("Content-Type", "")
            )["apkg"]
            deck_name, cards = parse_apkg(content, filename)
            deck_id = decks.save_import(user["id"], filename, deck_name, cards)
        except KeyError:
            return self.send_error(HTTPStatus.BAD_REQUEST, "No .apkg file was uploaded.")
        except (ValueError, sqlite3.DatabaseError, zipfile.BadZipFile) as error:
            return self.send_error(HTTPStatus.BAD_REQUEST, str(error))
        self.redirect(f"/deck/{deck_id}")

    def handle_progress(self, user: sqlite3.Row) -> None:
        try:
            payload = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
            card_id = int(payload["card_id"])
            result = "correct" if payload.get("result") == "correct" else "wrong"
        except (ValueError, KeyError, json.JSONDecodeError):
            return self.send_json({"ok": False}, HTTPStatus.BAD_REQUEST)
        decks.record_progress(user["id"], card_id, result)
        self.send_json({"ok": True})

    def handle_exam_submit(self, user: sqlite3.Row, deck_id: int) -> None:
        try:
            payload = self.read_json()
            raw_answers = payload.get("answers", {})
            if not isinstance(raw_answers, dict):
                raise ValueError("Answers must be an object.")
            answers = {int(card_id): int(option_index) for card_id, option_index in raw_answers.items()}
            results = decks.grade_exam(user["id"], deck_id, answers)
        except (LookupError, ValueError, TypeError):
            return self.send_json({"ok": False, "error": "Invalid exam submission."}, HTTPStatus.BAD_REQUEST)
        for result in results:
            decks.record_progress(user["id"], result["card_id"], "correct" if result["correct"] else "wrong")
        self.send_json(
            {"ok": True, "score": sum(result["correct"] for result in results), "results": results}
        )

    def handle_pdf_create(self, user: sqlite3.Row) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > PDF_MAX_SIZE_BYTES + 1024 * 1024:
            return self.send_json(
                {"ok": False, "error": "PDF upload is too large."}, HTTPStatus.REQUEST_ENTITY_TOO_LARGE
            )
        if pdf_repository.active_job_count(user["id"]) >= PDF_MAX_CONCURRENT_JOBS_PER_USER:
            return self.send_json(
                {"ok": False, "error": "You already have a PDF import in progress."}, HTTPStatus.CONFLICT
            )
        try:
            fields, files = parse_multipart_form(
                self.rfile.read(length), self.headers.get("Content-Type", "")
            )
            requested_mode = fields.get("mode", "")
            if requested_mode not in {"extract", "generate", "mock_exam"}:
                raise UploadValidationError("Choose a valid PDF import mode.")
            mode = "extract" if requested_mode == "mock_exam" else requested_mode
            kind = "mock_exam" if requested_mode == "mock_exam" else "flashcards"
            filename, content_type, content = files["pdf"]
            validate_pdf_upload(content, filename, content_type, PDF_MAX_SIZE_BYTES)
            if not self.pdf_manager:
                raise RuntimeError("PDF processing is not configured.")
            path = create_temporary_pdf(content)
            try:
                job_id = pdf_repository.create_job(user["id"], filename, mode, kind)
                self.pdf_manager.submit(job_id, user["id"], mode, path)
            except Exception:
                path.unlink(missing_ok=True)
                raise
        except KeyError:
            return self.send_json({"ok": False, "error": "No PDF file was uploaded."}, HTTPStatus.BAD_REQUEST)
        except (UploadValidationError, ValueError) as error:
            return self.send_json({"ok": False, "error": str(error)}, HTTPStatus.BAD_REQUEST)
        except RuntimeError as error:
            return self.send_json({"ok": False, "error": str(error)}, HTTPStatus.SERVICE_UNAVAILABLE)
        self.send_json({"ok": True, "job_id": job_id}, HTTPStatus.ACCEPTED)

    def handle_pdf_job_get(self, user: sqlite3.Row, job_id: str, include_drafts: bool) -> None:
        job = pdf_repository.get_job(user["id"], job_id)
        if not job:
            return self.send_json({"ok": False, "error": "PDF import not found."}, HTTPStatus.NOT_FOUND)
        draft_rows = pdf_repository.list_drafts(user["id"], job_id) if include_drafts else []
        payload: dict[str, Any] = {
            "ok": True,
            "job": pdf_repository.serialize_job(job, len(draft_rows) if include_drafts else None),
        }
        if include_drafts:
            payload["drafts"] = [
                {
                    **dict(row),
                    "accepted": bool(row["accepted"]),
                    "requires_input": bool(row["requires_input"]),
                }
                for row in draft_rows
            ]
        self.send_json(payload)

    def handle_pdf_cancel(self, user: sqlite3.Row, job_id: str) -> None:
        changed = pdf_repository.request_cancellation(user["id"], job_id)
        self.send_json({"ok": changed}, HTTPStatus.OK if changed else HTTPStatus.NOT_FOUND)

    def handle_pdf_approve(self, user: sqlite3.Row, job_id: str) -> None:
        try:
            deck_id = pdf_repository.approve_drafts(
                user["id"], job_id, str(self.read_json().get("deck_name", ""))
            )
        except (ValueError, json.JSONDecodeError) as error:
            return self.send_json({"ok": False, "error": str(error)}, HTTPStatus.BAD_REQUEST)
        self.send_json({"ok": True, "deck_id": deck_id}, HTTPStatus.CREATED)

    def serve_static(self, request_path: str) -> None:
        safe_name = posixpath.normpath(unquote(request_path)).removeprefix("/static/")
        file_path = STATIC_DIR / safe_name
        if not file_path.is_file() or STATIC_DIR not in file_path.resolve().parents:
            return self.send_error(HTTPStatus.NOT_FOUND)
        content_type = "text/css" if file_path.suffix == ".css" else "application/javascript"
        body = file_path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def create_handler(manager: PdfImportManager) -> type[Handler]:
    class ConfiguredHandler(Handler):
        pdf_manager = manager

    return ConfiguredHandler
