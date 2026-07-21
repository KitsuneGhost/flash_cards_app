from __future__ import annotations

import pytest

from flashcards import database


@pytest.fixture
def isolated_database(tmp_path, monkeypatch):
    path = tmp_path / "test.sqlite3"
    monkeypatch.setattr(database, "DB_PATH", path)
    database.init_db()
    return path
