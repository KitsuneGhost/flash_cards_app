"""Password, user, and session operations."""

from __future__ import annotations

import hashlib
import re
import secrets
import sqlite3

from .config import SESSION_DAYS
from .database import connect, now_iso


def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 310_000)
    return f"pbkdf2_sha256${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        algorithm, salt_hex, digest_hex = stored_hash.split("$", 2)
        salt = bytes.fromhex(salt_hex)
    except (ValueError, TypeError):
        return False
    if algorithm != "pbkdf2_sha256":
        return False
    expected = hash_password(password, salt).split("$", 2)[2]
    return secrets.compare_digest(expected, digest_hex)


def create_user(username: str, password: str) -> int:
    username = username.strip()
    if not re.fullmatch(r"[A-Za-z0-9_.-]{3,32}", username):
        raise ValueError("Use 3-32 letters, numbers, dots, underscores, or hyphens for your username.")
    if len(password) < 8:
        raise ValueError("Use a password with at least 8 characters.")
    with connect() as connection:
        try:
            cursor = connection.execute(
                "INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)",
                (username, hash_password(password), now_iso()),
            )
        except sqlite3.IntegrityError as error:
            raise ValueError("That username is already registered.") from error
    return int(cursor.lastrowid)


def authenticate_user(username: str, password: str) -> sqlite3.Row | None:
    with connect() as connection:
        user = connection.execute("SELECT * FROM users WHERE username = ?", (username.strip(),)).fetchone()
    return user if user and verify_password(password, user["password_hash"]) else None


def create_session(user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    with connect() as connection:
        connection.execute(
            """INSERT INTO sessions (token, user_id, created_at, expires_at)
               VALUES (?, ?, datetime('now'), datetime('now', ?))""",
            (token, user_id, f"+{SESSION_DAYS} days"),
        )
    return token


def get_session_user(token: str | None) -> sqlite3.Row | None:
    if not token:
        return None
    with connect() as connection:
        return connection.execute(
            """SELECT users.* FROM sessions
               JOIN users ON users.id = sessions.user_id
               WHERE sessions.token = ? AND sessions.expires_at > datetime('now')""",
            (token,),
        ).fetchone()


def delete_session(token: str | None) -> None:
    if token:
        with connect() as connection:
            connection.execute("DELETE FROM sessions WHERE token = ?", (token,))
