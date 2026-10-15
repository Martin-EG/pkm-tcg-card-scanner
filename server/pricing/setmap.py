"""Map TCGdex set ids to pokemontcg.io set ids (e.g. sv03.5 -> sv3pt5).

The two catalogs use different ids, so sets are matched on what both print:
1. same name and a release date within a week,
2. same printed set code and printed set size,
3. same name alone (unique on both sides).
Unmatched sets have no TCGplayer price; the employee enters one by hand.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date


# Sets the rules above can't match: names, codes, and sizes all differ.
SET_OVERRIDES = {
    "svp": "svp",  # "SVP Black Star Promos" vs "Scarlet & Violet Black Star Promos"
    "hgss3": "hgss3",  # "Undaunted" vs "HS—Undaunted"
    "hgss4": "hgss4",  # "Triumphant" vs "HS—Triumphant"
    "sve": "sve",  # "Scarlet & Violet Energy" vs "Scarlet & Violet Energies"
    "30th-c": "me55c",  # "30th Classic Collection" vs "30th Celebration: Classic Collection"
    "rc": "g1",  # Radiant Collection: on pokemontcg.io its RC1-RC32 cards are part of Generations
}


def _norm(name: str | None) -> str:
    name = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode()
    name = name.lower().replace("&", "and")
    name = re.sub(r"\b(the|pokemon|tcg)\b", "", name)
    return re.sub(r"[^a-z0-9]+", "", name)


def _date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value.replace("/", "-")[:10])
    except ValueError:
        return None


def build_set_map(tcgdex_sets: dict[str, dict], ptcg_sets: list[dict]) -> dict[str, str]:
    """tcgdex_sets: {set_id: {name, releaseDate, abbreviation, official_count}} (data/cache/sets_en.json);
    ptcg_sets: pokemontcg.io /v2/sets rows. Returns {tcgdex_set_id: ptcg_set_id}."""
    ptcg_ids = {p["id"] for p in ptcg_sets}
    out: dict[str, str] = {t: p for t, p in SET_OVERRIDES.items() if t in tcgdex_sets and p in ptcg_ids}
    used: set[str] = set(out.values())
    by_name: dict[str, list[dict]] = {}
    for p in ptcg_sets:
        by_name.setdefault(_norm(p["name"]), []).append(p)

    def take(tid: str, p: dict) -> None:
        out[tid] = p["id"]
        used.add(p["id"])

    # 1. name + date
    for tid, t in tcgdex_sets.items():
        if tid in out:
            continue
        td = _date(t.get("releaseDate"))
        for p in by_name.get(_norm(t.get("name")), []):
            pd = _date(p.get("releaseDate"))
            if td and pd and abs((td - pd).days) <= 7 and p["id"] not in used:
                take(tid, p)
                break
    # 2. printed code + printed size
    for tid, t in tcgdex_sets.items():
        if tid in out or not t.get("abbreviation"):
            continue
        hits = [p for p in ptcg_sets if p["id"] not in used and p.get("ptcgoCode") == t["abbreviation"]
                and p.get("printedTotal") == t.get("official_count")]
        if len(hits) == 1:
            take(tid, hits[0])
    # 3. unique name
    for tid, t in tcgdex_sets.items():
        if tid in out:
            continue
        hits = [p for p in by_name.get(_norm(t.get("name")), []) if p["id"] not in used]
        if len(hits) == 1:
            take(tid, hits[0])
    return out


def ptcg_card_id(ptcg_set_id: str, tcgdex_number: str) -> str:
    """pokemontcg.io card id: set id plus the printed number without leading zeros
    ("004" -> "4"); alphanumeric numbers keep their form ("TG01", "SWSH001")."""
    number = tcgdex_number.strip()
    if number.isdigit():
        number = str(int(number))
    return f"{ptcg_set_id}-{number}"
