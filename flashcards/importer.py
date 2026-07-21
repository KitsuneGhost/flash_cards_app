"""Safe conversion of Anki package data into application cards."""

from __future__ import annotations

import html
import json
import re
import sqlite3
import tempfile
import zipfile
from html.parser import HTMLParser
from pathlib import Path
from typing import Any


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
            key, value = key.lower(), value or ""
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
        elif not self.skip_depth and tag in self.allowed_tags:
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


def field_to_html(value: str) -> str:
    value = re.sub(r"\[sound:[^\]]+\]", "", value).replace("\x00", "").strip()
    if "<" in value and ">" in value:
        return sanitize_fragment(value)
    return html.escape(value).replace("\n", "<br>")


def _deck_names(collection_db: Path) -> dict[int, str]:
    with sqlite3.connect(collection_db) as connection:
        row = connection.execute("SELECT decks FROM col LIMIT 1").fetchone()
    if not row:
        return {}
    try:
        raw_decks = json.loads(row[0])
    except json.JSONDecodeError:
        return {}
    return {int(deck_id): deck.get("name", f"Deck {deck_id}") for deck_id, deck in raw_decks.items()}


def parse_apkg(upload: bytes, filename: str) -> tuple[str, list[dict[str, Any]]]:
    with tempfile.TemporaryDirectory() as temp_dir:
        archive_path = Path(temp_dir) / "upload.apkg"
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
            archive.extract(collection_name, temp_dir)

        collection_db = Path(temp_dir) / collection_name
        deck_names = _deck_names(collection_db)
        with sqlite3.connect(collection_db) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                """SELECT cards.id AS card_id, cards.nid, cards.did, cards.ord, notes.flds
                   FROM cards JOIN notes ON notes.id = cards.nid
                   ORDER BY cards.due, cards.id"""
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
