from __future__ import annotations

import hashlib
import html
import json
import os
import posixpath
import re
import secrets
import sqlite3
import tempfile
import zipfile
from datetime import datetime, UTC
from html.parser import HTMLParser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from http.cookies import SimpleCookie
from urllib.parse import parse_qs, quote, unquote, urlparse


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "flashcards.sqlite3"
STATIC_DIR = BASE_DIR / "static"
MAX_UPLOAD_BYTES = 100 * 1024 * 1024


def env(name: str, default: str) -> str:
    return os.environ.get(name, default)


HOST = env("FLASHCARDS_HOST", "127.0.0.1")
PORT = int(env("FLASHCARDS_PORT", "8000"))
SESSION_COOKIE = "flashcards_session"
SESSION_DAYS = 14


class Sanitizer(HTMLParser):
    allowed_tags = {
        "a",
        "b",
        "blockquote",
        "br",
        "code",
        "div",
        "em",
        "i",
        "li",
        "ol",
        "p",
        "pre",
        "span",
        "strong",
        "sub",
        "sup",
        "table",
        "tbody",
        "td",
        "th",
        "thead",
        "tr",
        "u",
        "ul",
    }
    allowed_attrs = {"class", "href"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in {"script", "style", "iframe", "object", "embed"}:
            self.skip_depth += 1
            return
        if self.skip_depth or tag not in self.allowed_tags:
            return

        safe_attrs = []
        for key, value in attrs:
            key = key.lower()
            value = value or ""
            if key not in self.allowed_attrs or key.startswith("on"):
                continue
            if key == "href" and not value.startswith(("http://", "https://", "mailto:", "#")):
                continue
            safe_attrs.append(f'{key}="{html.escape(value, quote=True)}"')

        attr_text = (" " + " ".join(safe_attrs)) if safe_attrs else ""
        self.parts.append(f"<{tag}{attr_text}>")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"script", "style", "iframe", "object", "embed"}:
            self.skip_depth = max(0, self.skip_depth - 1)
            return
        if not self.skip_depth and tag in self.allowed_tags:
            self.parts.append(f"</{tag}>")

    def handle_data(self, data: str) -> None:
        if not self.skip_depth:
            self.parts.append(html.escape(data))

    def handle_entityref(self, name: str) -> None:
        if not self.skip_depth:
            self.parts.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        if not self.skip_depth:
            self.parts.append(f"&#{name};")


def sanitize_fragment(value: str) -> str:
    parser = Sanitizer()
    parser.feed(value)
    parser.close()
    return "".join(parser.parts).strip()


def strip_anki_markup(value: str) -> str:
    value = re.sub(r"\[sound:[^\]]+\]", "", value)
    value = value.replace("\x00", "")
    return value.strip()


def field_to_html(value: str) -> str:
    value = strip_anki_markup(value)
    if "<" in value and ">" in value:
        return sanitize_fragment(value)
    return html.escape(value).replace("\n", "<br>")


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 310_000)
    return f"pbkdf2_sha256${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        algorithm, salt_hex, digest_hex = stored_hash.split("$", 2)
    except ValueError:
        return False
    if algorithm != "pbkdf2_sha256":
        return False
    expected = hash_password(password, bytes.fromhex(salt_hex)).split("$", 2)[2]
    return secrets.compare_digest(expected, digest_hex)


def db() -> sqlite3.Connection:
    DATA_DIR.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    with db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS sessions (
                token TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS decks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                name TEXT NOT NULL,
                source_filename TEXT NOT NULL,
                card_count INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS cards (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                deck_id INTEGER NOT NULL REFERENCES decks(id) ON DELETE CASCADE,
                source_card_id INTEGER,
                source_note_id INTEGER,
                front TEXT NOT NULL,
                back TEXT NOT NULL,
                position INTEGER NOT NULL DEFAULT 0,
                seen_count INTEGER NOT NULL DEFAULT 0,
                correct_count INTEGER NOT NULL DEFAULT 0,
                wrong_count INTEGER NOT NULL DEFAULT 0,
                last_result TEXT,
                updated_at TEXT
            );
            """
        )
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(decks)").fetchall()}
        if "user_id" not in columns:
            conn.execute("ALTER TABLE decks ADD COLUMN user_id INTEGER REFERENCES users(id) ON DELETE CASCADE")


def parse_deck_names(collection_db: Path) -> dict[int, str]:
    with sqlite3.connect(collection_db) as conn:
        row = conn.execute("SELECT decks FROM col LIMIT 1").fetchone()
    if not row:
        return {}
    try:
        raw_decks = json.loads(row[0])
    except json.JSONDecodeError:
        return {}
    return {int(deck_id): deck.get("name", f"Deck {deck_id}") for deck_id, deck in raw_decks.items()}


def parse_apkg(upload: bytes, filename: str) -> tuple[str, list[dict[str, Any]]]:
    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        archive_path = temp / "upload.apkg"
        archive_path.write_bytes(upload)

        if not zipfile.is_zipfile(archive_path):
            raise ValueError("That file is not a valid .apkg archive.")

        with zipfile.ZipFile(archive_path) as archive:
            collection_name = next(
                (name for name in ("collection.anki21", "collection.anki2") if name in archive.namelist()),
                None,
            )
            if not collection_name:
                raise ValueError("This .apkg does not contain an Anki collection database.")
            archive.extract(collection_name, temp)

        collection_db = temp / collection_name
        deck_names = parse_deck_names(collection_db)

        with sqlite3.connect(collection_db) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT cards.id AS card_id, cards.nid, cards.did, cards.ord, notes.flds
                FROM cards
                JOIN notes ON notes.id = cards.nid
                ORDER BY cards.due, cards.id
                """
            ).fetchall()

        deck_title = Path(filename).stem or "Imported deck"
        cards = []
        for index, row in enumerate(rows):
            fields = [field_to_html(field) for field in row["flds"].split("\x1f")]
            visible_fields = [field for field in fields if field]
            if not visible_fields:
                continue

            front = visible_fields[0]
            remaining = visible_fields[1:] or visible_fields[:1]
            back = "".join(f'<div class="field-block">{field}</div>' for field in remaining)
            deck_title = deck_names.get(int(row["did"]), deck_title)
            cards.append(
                {
                    "source_card_id": int(row["card_id"]),
                    "source_note_id": int(row["nid"]),
                    "front": front,
                    "back": back,
                    "position": index,
                }
            )

    if not cards:
        raise ValueError("No studyable cards were found in that .apkg file.")
    return deck_title, cards


def create_user(username: str, password: str) -> int:
    username = username.strip()
    if not re.fullmatch(r"[A-Za-z0-9_.-]{3,32}", username):
        raise ValueError("Use 3-32 letters, numbers, dots, underscores, or hyphens for your username.")
    if len(password) < 8:
        raise ValueError("Use a password with at least 8 characters.")
    with db() as conn:
        try:
            cursor = conn.execute(
                """
                INSERT INTO users (username, password_hash, created_at)
                VALUES (?, ?, ?)
                """,
                (username, hash_password(password), now_iso()),
            )
        except sqlite3.IntegrityError as error:
            raise ValueError("That username is already registered.") from error
    return int(cursor.lastrowid)


def authenticate_user(username: str, password: str) -> sqlite3.Row | None:
    with db() as conn:
        user = conn.execute("SELECT * FROM users WHERE username = ?", (username.strip(),)).fetchone()
    if user and verify_password(password, user["password_hash"]):
        return user
    return None


def create_session(user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    with db() as conn:
        conn.execute(
            """
            INSERT INTO sessions (token, user_id, created_at, expires_at)
            VALUES (?, ?, datetime('now'), datetime('now', ?))
            """,
            (token, user_id, f"+{SESSION_DAYS} days"),
        )
    return token


def get_session_user(token: str | None) -> sqlite3.Row | None:
    if not token:
        return None
    with db() as conn:
        user = conn.execute(
            """
            SELECT users.*
            FROM sessions
            JOIN users ON users.id = sessions.user_id
            WHERE sessions.token = ? AND sessions.expires_at > datetime('now')
            """,
            (token,),
        ).fetchone()
    return user


def delete_session(token: str | None) -> None:
    if token:
        with db() as conn:
            conn.execute("DELETE FROM sessions WHERE token = ?", (token,))


def save_import(user_id: int, filename: str, deck_name: str, cards: list[dict[str, Any]]) -> int:
    with db() as conn:
        cursor = conn.execute(
            """
            INSERT INTO decks (user_id, name, source_filename, card_count, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (user_id, deck_name, filename, len(cards), now_iso()),
        )
        deck_id = int(cursor.lastrowid)
        conn.executemany(
            """
            INSERT INTO cards (
                deck_id, source_card_id, source_note_id, front, back, position, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    deck_id,
                    card["source_card_id"],
                    card["source_note_id"],
                    card["front"],
                    card["back"],
                    card["position"],
                    now_iso(),
                )
                for card in cards
            ],
        )
    return deck_id


def render_page(title: str, body: str, user: sqlite3.Row | None = None, extra_head: str = "") -> bytes:
    nav = (
        f"""
        <span class="auth-note">{html.escape(user["username"])}</span>
        <form action="/logout" method="post">
          <button class="link-button" type="submit">Log out</button>
        </form>
        """
        if user
        else """
        <a class="nav-link" href="/login">Log in</a>
        <a class="button compact" href="/register">Register</a>
        """
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)} · Flash Cards</title>
  <link rel="stylesheet" href="/static/styles.css">
  {extra_head}
</head>
<body>
  <header class="topbar">
    <a class="brand" href="/">Flash Cards</a>
    <nav class="nav-actions">{nav}</nav>
  </header>
  <main>{body}</main>
</body>
</html>""".encode()


def render_auth_page(mode: str, message: str = "", next_path: str = "/") -> bytes:
    is_register = mode == "register"
    title = "Create account" if is_register else "Log in"
    action = "/register" if is_register else "/login"
    prompt = "Already have an account?" if is_register else "Need an account?"
    link_href = "/login" if is_register else "/register"
    link_text = "Log in" if is_register else "Register"
    notice = f'<div class="notice error">{html.escape(message)}</div>' if message else ""
    body = f"""
    <section class="auth-shell">
      <form class="auth-panel" action="{action}" method="post">
        <div>
          <h1>{title}</h1>
          <p>Import and study your Anki decks from your own account.</p>
        </div>
        {notice}
        <label for="username">Username</label>
        <input id="username" name="username" autocomplete="username" required>
        <label for="password">Password</label>
        <input id="password" name="password" type="password" autocomplete="{"new-password" if is_register else "current-password"}" required>
        <input name="next" type="hidden" value="{html.escape(next_path, quote=True)}">
        <button type="submit">{title}</button>
        <p class="auth-switch">{prompt} <a href="{link_href}">{link_text}</a></p>
      </form>
    </section>
    """
    return render_page(title, body)


def render_dashboard(user: sqlite3.Row, message: str = "") -> bytes:
    with db() as conn:
        decks = conn.execute(
            """
            SELECT decks.*,
                   COALESCE(SUM(cards.seen_count), 0) AS total_seen,
                   COALESCE(SUM(cards.correct_count), 0) AS total_correct
            FROM decks
            LEFT JOIN cards ON cards.deck_id = decks.id
            WHERE decks.user_id = ?
            GROUP BY decks.id
            ORDER BY decks.created_at DESC
            """,
            (user["id"],),
        ).fetchall()

    deck_items = []
    for deck in decks:
        accuracy = "No reviews yet"
        if deck["total_seen"]:
            percent = round((deck["total_correct"] / deck["total_seen"]) * 100)
            accuracy = f"{percent}% correct"
        deck_items.append(
            f"""
            <article class="deck-card">
              <div>
                <h2>{html.escape(deck["name"])}</h2>
                <p>{deck["card_count"]} cards · {accuracy}</p>
              </div>
              <a class="button" href="/deck/{deck["id"]}">Study</a>
            </article>
            """
        )

    empty = "" if deck_items else '<p class="empty">Import an Anki package to start studying.</p>'
    notice = f'<div class="notice">{html.escape(message)}</div>' if message else ""
    body = f"""
    <section class="dashboard">
      <div class="intro">
        <h1>Your decks</h1>
        <p>Import an Anki <code>.apkg</code> file, then study cards right in the browser.</p>
      </div>
      {notice}
      <form class="upload-panel" action="/upload" method="post" enctype="multipart/form-data">
        <label for="apkg">Anki package</label>
        <div class="upload-row">
          <input id="apkg" name="apkg" type="file" accept=".apkg,application/zip" required>
          <button type="submit">Import</button>
        </div>
      </form>
      <section class="deck-grid">
        {''.join(deck_items)}
        {empty}
      </section>
    </section>
    """
    return render_page("Decks", body, user=user)


def render_study(user: sqlite3.Row, deck_id: int) -> bytes:
    with db() as conn:
        deck = conn.execute("SELECT * FROM decks WHERE id = ? AND user_id = ?", (deck_id, user["id"])).fetchone()
        cards = conn.execute(
            """
            SELECT id, front, back, seen_count, correct_count, wrong_count
            FROM cards
            WHERE deck_id = ?
            ORDER BY position, id
            """,
            (deck_id,),
        ).fetchall()

    if not deck:
        raise LookupError("Deck not found")

    payload = json.dumps([dict(card) for card in cards])
    body = f"""
    <section class="study-shell">
      <div class="study-head">
        <div>
          <a class="back-link" href="/">Back to decks</a>
          <h1>{html.escape(deck["name"])}</h1>
        </div>
        <div class="counter"><span id="cardNumber">1</span> / {len(cards)}</div>
      </div>
      <div class="progress"><div id="progressBar"></div></div>
      <article id="studyCard" class="study-card" tabindex="0" aria-live="polite">
        <div class="side-label" id="sideLabel">Front</div>
        <div id="cardContent" class="card-content"></div>
      </article>
      <div class="actions">
        <button id="flipButton" type="button">Flip</button>
        <button id="wrongButton" type="button" class="secondary">Again</button>
        <button id="rightButton" type="button">Got it</button>
      </div>
    </section>
    <script>window.FLASHCARDS = {payload};</script>
    <script src="/static/study.js"></script>
    """
    return render_page(str(deck["name"]), body, user=user)


def parse_multipart(body: bytes, content_type: str) -> dict[str, tuple[str, bytes]]:
    match = re.search(r"boundary=(?P<boundary>[^;]+)", content_type)
    if not match:
        raise ValueError("Missing multipart boundary.")
    boundary = match.group("boundary").strip('"').encode()
    delimiter = b"--" + boundary
    files: dict[str, tuple[str, bytes]] = {}

    for part in body.split(delimiter):
        part = part.strip()
        if not part or part == b"--":
            continue
        if part.endswith(b"--"):
            part = part[:-2].strip()
        header_blob, _, content = part.partition(b"\r\n\r\n")
        if not header_blob:
            continue
        headers = header_blob.decode("utf-8", "replace").split("\r\n")
        disposition = next((h for h in headers if h.lower().startswith("content-disposition:")), "")
        name_match = re.search(r'name="([^"]+)"', disposition)
        filename_match = re.search(r'filename="([^"]*)"', disposition)
        if not name_match or not filename_match:
            continue
        content = content.removesuffix(b"\r\n")
        files[name_match.group(1)] = (Path(filename_match.group(1)).name, content)
    return files


class Handler(BaseHTTPRequestHandler):
    server_version = "FlashCards/0.1"

    def log_message(self, format: str, *args: Any) -> None:
        print(f"{self.address_string()} - {format % args}")

    def session_token(self) -> str | None:
        cookie = SimpleCookie(self.headers.get("Cookie", ""))
        morsel = cookie.get(SESSION_COOKIE)
        return morsel.value if morsel else None

    def current_user(self) -> sqlite3.Row | None:
        return get_session_user(self.session_token())

    def require_user(self) -> sqlite3.Row | None:
        user = self.current_user()
        if user:
            return user
        self.redirect(f"/login?next={quote(self.path)}")
        return None

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

    def set_session_cookie(self, token: str) -> None:
        self.send_header(
            "Set-Cookie",
            f"{SESSION_COOKIE}={token}; HttpOnly; SameSite=Lax; Path=/; Max-Age={SESSION_DAYS * 24 * 60 * 60}",
        )

    def clear_session_cookie(self) -> None:
        self.send_header("Set-Cookie", f"{SESSION_COOKIE}=; HttpOnly; SameSite=Lax; Path=/; Max-Age=0")

    def redirect_with_cookie(self, path: str, token: str | None = None, clear: bool = False) -> None:
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", path)
        if token:
            self.set_session_cookie(token)
        if clear:
            self.clear_session_cookie()
        self.end_headers()

    def read_form(self) -> dict[str, str]:
        content_length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(content_length).decode("utf-8", "replace")
        parsed = parse_qs(raw, keep_blank_values=True)
        return {key: values[0] for key, values in parsed.items()}

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        try:
            if parsed.path.startswith("/static/"):
                self.serve_static(parsed.path)
            elif parsed.path == "/login":
                if self.current_user():
                    self.redirect("/")
                    return
                query = parse_qs(parsed.query)
                message = query.get("message", [""])[0]
                next_path = query.get("next", ["/"])[0]
                self.send_html(render_auth_page("login", message, next_path))
            elif parsed.path == "/register":
                if self.current_user():
                    self.redirect("/")
                    return
                message = parse_qs(parsed.query).get("message", [""])[0]
                self.send_html(render_auth_page("register", message))
            elif parsed.path == "/":
                user = self.require_user()
                if not user:
                    return
                message = parse_qs(parsed.query).get("message", [""])[0]
                self.send_html(render_dashboard(user, message))
            elif parsed.path.startswith("/deck/"):
                user = self.require_user()
                if not user:
                    return
                deck_id = int(parsed.path.removeprefix("/deck/").strip("/"))
                self.send_html(render_study(user, deck_id))
            else:
                self.send_error(HTTPStatus.NOT_FOUND)
        except (LookupError, ValueError):
            self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/register":
            self.handle_register()
        elif parsed.path == "/login":
            self.handle_login()
        elif parsed.path == "/logout":
            delete_session(self.session_token())
            self.redirect_with_cookie("/login", clear=True)
        elif parsed.path == "/upload":
            user = self.require_user()
            if user:
                self.handle_upload(user)
        elif parsed.path == "/api/progress":
            user = self.require_user()
            if user:
                self.handle_progress(user)
        else:
            self.send_error(HTTPStatus.NOT_FOUND)

    def handle_register(self) -> None:
        form = self.read_form()
        try:
            user_id = create_user(form.get("username", ""), form.get("password", ""))
        except ValueError as error:
            self.redirect(f"/register?message={quote(str(error))}")
            return
        token = create_session(user_id)
        self.redirect_with_cookie("/", token=token)

    def handle_login(self) -> None:
        form = self.read_form()
        user = authenticate_user(form.get("username", ""), form.get("password", ""))
        if not user:
            self.redirect("/login?message=Invalid%20username%20or%20password.")
            return
        next_path = form.get("next") or "/"
        if not next_path.startswith("/") or next_path.startswith("//"):
            next_path = "/"
        token = create_session(user["id"])
        self.redirect_with_cookie(next_path, token=token)

    def handle_upload(self, user: sqlite3.Row) -> None:
        content_length = int(self.headers.get("Content-Length", "0"))
        if content_length <= 0 or content_length > MAX_UPLOAD_BYTES:
            self.send_error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "Upload must be under 100 MB.")
            return

        try:
            files = parse_multipart(self.rfile.read(content_length), self.headers.get("Content-Type", ""))
            filename, content = files["apkg"]
            deck_name, cards = parse_apkg(content, filename)
            deck_id = save_import(user["id"], filename, deck_name, cards)
        except KeyError:
            self.send_error(HTTPStatus.BAD_REQUEST, "No .apkg file was uploaded.")
            return
        except (ValueError, sqlite3.DatabaseError, zipfile.BadZipFile) as error:
            self.send_error(HTTPStatus.BAD_REQUEST, str(error))
            return

        self.redirect(f"/deck/{deck_id}")

    def handle_progress(self, user: sqlite3.Row) -> None:
        content_length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(content_length)
        try:
            payload = json.loads(raw)
            card_id = int(payload["card_id"])
            result = "correct" if payload.get("result") == "correct" else "wrong"
        except (ValueError, KeyError, json.JSONDecodeError):
            self.send_json({"ok": False}, HTTPStatus.BAD_REQUEST)
            return

        column = "correct_count" if result == "correct" else "wrong_count"
        with db() as conn:
            conn.execute(
                f"""
                UPDATE cards
                SET seen_count = seen_count + 1,
                    {column} = {column} + 1,
                    last_result = ?,
                    updated_at = ?
                WHERE id = ?
                  AND deck_id IN (SELECT id FROM decks WHERE user_id = ?)
                """,
                (result, now_iso(), card_id, user["id"]),
            )
        self.send_json({"ok": True})

    def serve_static(self, request_path: str) -> None:
        safe_name = posixpath.normpath(unquote(request_path)).removeprefix("/static/")
        file_path = STATIC_DIR / safe_name
        if not file_path.is_file() or STATIC_DIR not in file_path.resolve().parents:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        content_type = "text/css" if file_path.suffix == ".css" else "application/javascript"
        body = file_path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    init_db()
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Flash Cards running at http://{HOST}:{PORT}")
    print("Create an account at /register, then log in to import and study decks.")
    server.serve_forever()


if __name__ == "__main__":
    main()
