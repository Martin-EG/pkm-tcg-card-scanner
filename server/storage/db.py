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
CREATE TABLE IF NOT EXISTS price_cache (
    card_id TEXT NOT NULL,          -- TCGdex id
    variant TEXT NOT NULL,          -- '' marks "looked up, no price"
    market_usd REAL,
    provider TEXT,                  -- API that supplied the TCGplayer price: tcgdex | pokemontcg
    price_date TEXT,                -- when TCGplayer last updated the price
    fetched_on TEXT NOT NULL,       -- local date of the lookup
    PRIMARY KEY (card_id, variant, fetched_on)
);
CREATE TABLE IF NOT EXISTS fx_rates (
    series TEXT NOT NULL,
    rate_date TEXT NOT NULL,        -- date Banxico published the rate for
    rate REAL NOT NULL,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (series, rate_date)
);
CREATE TABLE IF NOT EXISTS buy_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    currency TEXT NOT NULL,         -- MXN or USD, fixed when the session opens
    fx_rate REAL,                   -- NULL when CONVERT_TO_MXN is false
    fx_date TEXT,
    fx_series TEXT,
    fx_stale INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS session_cards (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES buy_sessions(id),
    scan_id INTEGER,
    card_index INTEGER,
    card_id TEXT NOT NULL,
    catalog_language TEXT NOT NULL, -- language of the catalog entry (en for now)
    printed_language TEXT NOT NULL, -- language printed on the card (es/ja flagged by OCR)
    name TEXT, set_name TEXT, number TEXT,
    condition TEXT NOT NULL,
    variant TEXT,
    variants TEXT,                  -- JSON list of variants that have a price
    price_usd REAL,                 -- price the offer used, NULL when none
    price_source TEXT,              -- tcgplayer | manual
    price_provider TEXT,            -- API that supplied the TCGplayer price: tcgdex | pokemontcg
    price_date TEXT,                -- TCGplayer update date, or the day it was entered by hand
    price_manual INTEGER NOT NULL DEFAULT 0,
    price_approximate INTEGER NOT NULL DEFAULT 0, -- English price used for a Spanish card
    price_stale INTEGER NOT NULL DEFAULT 0,       -- old cached price, API offline
    fx_rate REAL,                   -- rate the offer used; NULL without conversion
    fx_date TEXT,
    currency TEXT NOT NULL,
    market REAL, cash_offer REAL, credit_offer REAL,
    buying INTEGER,                 -- 0: below the minimum; NULL: no price yet
    accepted INTEGER NOT NULL DEFAULT 1,
    removed_at TEXT,                -- set when the employee removes the card; kept for review
    ebay_url TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
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
        # Columns added after a table was first created (CREATE IF NOT EXISTS skips them).
        self._ensure_column("price_cache", "provider", "TEXT")
        self._ensure_column("session_cards", "price_provider", "TEXT")
        self._ensure_column("session_cards", "removed_at", "TEXT")

    def _ensure_column(self, table: str, column: str, kind: str) -> None:
        columns = {r[1] for r in self.conn.execute(f"PRAGMA table_info({table})")}
        if column not in columns:
            self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {kind}")
            self.conn.commit()

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
