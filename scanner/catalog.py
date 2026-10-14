"""Card catalogs (data/catalog_<lang>.jsonl) joined with set info (data/cache/sets_<lang>.json)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from scanner.ocr import CardMeta, normalize_number

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"


@dataclass
class Catalog:
    lang: str
    rows: dict[str, dict]  # card id -> catalog row
    metas: dict[str, CardMeta]
    set_codes: set[str]
    promo_prefixes: set[str]


def load_catalog(lang: str, data_dir: Path = DATA) -> Catalog:
    rows = {}
    for line in (data_dir / f"catalog_{lang}.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            rows[row["id"]] = row
    sets_path = data_dir / "cache" / f"sets_{lang}.json"
    sets = json.loads(sets_path.read_text(encoding="utf-8")) if sets_path.exists() else {}
    metas = {}
    for cid, r in rows.items():
        s = sets.get(r["set"], {})
        metas[cid] = CardMeta(cid, lang, r["name"], r["set"], normalize_number(r["number"]),
                              s.get("abbreviation"), s.get("official_count"))
    prefixes = set()
    for m in metas.values():
        match = re.fullmatch(r"([A-Z]+)\d+", m.number)
        if match:
            prefixes.add(match.group(1))
    codes = {m.set_code for m in metas.values() if m.set_code}
    return Catalog(lang, rows, metas, codes, prefixes)
