"""SQLite storage for scans (photo + result) and employee corrections."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS scans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    photo_path TEXT NOT NULL,
    error TEXT,
    seconds REAL
);
CREATE TABLE IF NOT EXISTS scan_cards (
    scan_id INTEGER NOT NULL REFERENCES scans(id),
    card_index INTEGER NOT NULL,
    crop_path TEXT NOT NULL,
    language TEXT,
    top_card_id TEXT,
    confident INTEGER NOT NULL,
    ocr_used INTEGER NOT NULL,
    candidates TEXT NOT NULL,
    PRIMARY KEY (scan_id, card_index)
);
CREATE TABLE IF NOT EXISTS corrections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    scan_id INTEGER NOT NULL REFERENCES scans(id),
    card_index INTEGER NOT NULL,
    card_id TEXT NOT NULL,
    language TEXT NOT NULL,
    proposed_card_id TEXT
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)

    def add_scan(self, photo_path: str) -> int:
        cur = self.conn.execute("INSERT INTO scans (created_at, photo_path) VALUES (?, ?)", (_now(), photo_path))
        self.conn.commit()
        return int(cur.lastrowid)

    def finish_scan(self, scan_id: int, seconds: float, error: str | None = None) -> None:
        self.conn.execute("UPDATE scans SET seconds = ?, error = ? WHERE id = ?", (seconds, error, scan_id))
        self.conn.commit()

    def add_card(self, scan_id: int, index: int, crop_path: str, language: str | None, top_card_id: str | None,
                 confident: bool, ocr_used: bool, candidates: list[dict]) -> None:
        self.conn.execute(
            "INSERT INTO scan_cards VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (scan_id, index, crop_path, language, top_card_id, int(confident), int(ocr_used), json.dumps(candidates)),
        )
        self.conn.commit()

    def get_card(self, scan_id: int, index: int) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM scan_cards WHERE scan_id = ? AND card_index = ?", (scan_id, index)
        ).fetchone()

    def add_correction(self, scan_id: int, index: int, card_id: str, language: str, proposed: str | None) -> int:
        cur = self.conn.execute(
            "INSERT INTO corrections (created_at, scan_id, card_index, card_id, language, proposed_card_id)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (_now(), scan_id, index, card_id, language, proposed),
        )
        self.conn.commit()
        return int(cur.lastrowid)
