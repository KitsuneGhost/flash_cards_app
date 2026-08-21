"""Safe conversion of Anki package data into application cards."""

from __future__ import annotations

import html
import base64
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


def _note_models(collection_db: Path) -> dict[int, dict[str, Any]]:
    with sqlite3.connect(collection_db) as connection:
        row = connection.execute("SELECT models FROM col LIMIT 1").fetchone()
    if not row:
        return {}
    try:
        models = json.loads(row[0])
    except (TypeError, json.JSONDecodeError):
        return {}
    return {int(model_id): model for model_id, model in models.items()}


def _template_fields(template: str) -> list[str]:
    """Return note fields referenced by an Anki template, in display order."""
    found: list[str] = []
    for expression in re.findall(r"{{([^{}]+)}}", template):
        expression = expression.strip().lstrip("#^/").strip()
        field_name = expression.rsplit(":", 1)[-1].strip()
        if field_name and field_name != "FrontSide" and field_name not in found:
            found.append(field_name)
    return found


def _is_machine_field(value: str) -> bool:
    """Recognize data used by scripted Anki templates but not shown as card text."""
    plain = re.sub(r"<[^>]+>", "", html.unescape(value)).strip()
    if not plain:
        return False
    lowered = plain.casefold()
    if lowered in {"dynamic", "fixed"}:
        return True
    if re.fullmatch(r"[A-E]", plain):
        return True
    if re.fullmatch(r"[a-z][a-z0-9_-]*::[a-f0-9-]{8,}", lowered):
        return True
    if plain.count("::") >= 2:
        return True
    if " > " in plain and len(plain) > 80:
        return True
    if re.fullmatch(r"[A-Za-z0-9_+/=-]+", plain) and len(plain) >= 32:
        try:
            decoded = base64.b64decode(plain, validate=True).lstrip()
        except (ValueError, base64.binascii.Error):
            pass
        else:
            if decoded.startswith((b"[", b"{")):
                return True
    if lowered.startswith("label-dependent option text requires "):
        return True
    return False


def _human_fields(values: list[str]) -> list[str]:
    return [value for value in values if value.strip() and not _is_machine_field(value)]


def _prefer_semantic_fields(names: list[str], side: str) -> list[str]:
    terms = (
        ("question", "prompt", "stem", "front", "option", "choice")
        if side == "front"
        else ("answer", "back", "explanation", "rationale", "solution", "extra")
    )
    preferred = [
        name
        for name in names
        if any(term in name.casefold() for term in terms)
        or (side == "front" and re.fullmatch(r"[A-H]", name.strip(), re.IGNORECASE))
    ]
    return preferred or names


def _selected_fields(
    raw_fields: list[str], model: dict[str, Any] | None, template_ordinal: int
) -> tuple[list[str], list[str]]:
    """Choose front/back values using the card template instead of hidden note fields."""
    if not model:
        visible = [field for field in raw_fields if field.strip()]
        return visible[:1], visible[1:] or visible[:1]

    field_names = [field.get("name", "") for field in model.get("flds", [])]
    values = dict(zip(field_names, raw_fields, strict=False))
    if {"Stem", "CorrectOptionLabels", "Explanation"}.issubset(values) and any(
        f"Option{label}" in values for label in "ABCDEFG"
    ):
        front = [values["Stem"]]
        front.extend(
            f"{label}. {values[f'Option{label}']}"
            for label in "ABCDEFG"
            if values.get(f"Option{label}", "").strip()
        )
        correct_labels = values["CorrectOptionLabels"].strip()
        correct_answer = values.get("CorrectAnswerHuman", "").strip()
        if not correct_answer and len(correct_labels) == 1:
            correct_answer = values.get(f"Option{correct_labels}", "").strip()
        answer_heading = "Correct answer"
        if correct_labels:
            answer_heading += f" ({correct_labels})"
        back = [f"{answer_heading}: {correct_answer}".rstrip()] if correct_answer else []
        if values["Explanation"].strip():
            back.append(f"Explanation: {values['Explanation']}")
        return _human_fields(front), _human_fields(back) or _human_fields(front)

    templates = model.get("tmpls", [])
    if not templates:
        return _selected_fields(raw_fields, None, template_ordinal)
    template = templates[min(template_ordinal, len(templates) - 1)]
    question_names = _template_fields(template.get("qfmt", ""))
    answer_names = _template_fields(template.get("afmt", ""))
    question_names = _prefer_semantic_fields(question_names, "front")
    front = _human_fields([values[name] for name in question_names if values.get(name, "").strip()])
    back_names = [name for name in answer_names if name not in question_names]
    # Cloze templates deliberately use the same field on both sides.
    is_cloze = model.get("type") == 1
    if is_cloze:
        back_names = answer_names
    if not is_cloze:
        back_names = _prefer_semantic_fields(back_names, "back")
    back = _human_fields([values[name] for name in back_names if values.get(name, "").strip()])
    if not front:
        return _selected_fields(raw_fields, None, template_ordinal)
    return front, back or front


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
        note_models = _note_models(collection_db)
        with sqlite3.connect(collection_db) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                """SELECT cards.id AS card_id, cards.nid, cards.did, cards.ord,
                          notes.mid, notes.flds
                   FROM cards JOIN notes ON notes.id = cards.nid
                   ORDER BY cards.due, cards.id"""
            ).fetchall()

        deck_title = Path(filename).stem or "Imported deck"
        cards = []
        for index, row in enumerate(rows):
            front_fields, back_fields = _selected_fields(
                row["flds"].split("\x1f"), note_models.get(int(row["mid"])), int(row["ord"])
            )
            if not front_fields:
                continue
            front = "".join(
                f'<div class="field-block">{field_to_html(field)}</div>' for field in front_fields
            )
            back = "".join(
                f'<div class="field-block">{field_to_html(field)}</div>' for field in back_fields
            )
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
