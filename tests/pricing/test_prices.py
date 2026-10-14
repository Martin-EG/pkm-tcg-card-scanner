"""Price lookup: TCGdex first, pokemontcg.io as backup, with a daily cache that keeps
the counter working offline."""

import json
from datetime import date
from pathlib import Path

import pytest

from server.storage.db import Store
from server.pricing.prices import PokemonTcgProvider, PriceService
from server.pricing.quote import PriceUnavailable, TcgplayerQuote

FIX = Path(__file__).resolve().parents[1] / "fixtures"
ROWS = {
    "sv03.5-004": {"id": "sv03.5-004", "set": "sv03.5", "number": "004", "name": "Charmander"},
    "sv03.5-005": {"id": "sv03.5-005", "set": "sv03.5", "number": "005", "name": "Charmeleon"},
    "sv03.5-006": {"id": "sv03.5-006", "set": "sv03.5", "number": "006", "name": "Charizard ex"},
    "zzz-001": {"id": "zzz-001", "set": "zzz", "number": "001", "name": "Unmapped"},
}


class FakeTcgdex:
    name = "tcgdex"

    def __init__(self):
        self.calls, self.down = [], False
        self.quotes = {
            "sv03.5-004": TcgplayerQuote("sv03.5-004", {"normal": 0.26, "reverseHolofoil": 0.69}, "2026-10-13", None),
        }

    def quote(self, card_id):
        self.calls.append(card_id)
        if self.down:
            raise PriceUnavailable("offline")
        return self.quotes.get(card_id)


class FakePtcgClient:
    """pokemontcg.io client: knows sv3pt5-6 (which TCGdex can't price)."""

    def __init__(self):
        self.calls, self.down = [], False
        self.quotes = {"sv3pt5-4": TcgplayerQuote("sv3pt5-4", {"normal": 0.30}, "2026-10-14", None),
                       "sv3pt5-6": TcgplayerQuote("sv3pt5-6", {"holofoil": 5.0}, "2026-10-14", None)}

    def quote(self, ptcg_id):
        self.calls.append(ptcg_id)
        if self.down:
            raise PriceUnavailable("offline")
        return self.quotes.get(ptcg_id)


@pytest.fixture
def svc(tmp_path):
    day = {"d": date(2026, 10, 14)}
    ptcg_path = tmp_path / "ptcg_sets.json"
    ptcg_path.write_text((FIX / "ptcg_sets_sample.json").read_text())
    tcgdex_sets = json.loads((FIX / "tcgdex_sets_sample.json").read_text())
    primary, backup_client = FakeTcgdex(), FakePtcgClient()
    backup = PokemonTcgProvider(backup_client, ROWS, tcgdex_sets, ptcg_path)
    s = PriceService(Store(tmp_path / "db.sqlite").conn, [primary, backup], today=lambda: day["d"])
    s.day, s.primary, s.backup = day, primary, backup_client
    return s


def test_tcgdex_is_tried_first(svc):
    p = svc.lookup("sv03.5-004")
    assert p.status == "ok" and p.provider == "tcgdex" and p.source == "tcgplayer"
    assert p.prices == {"normal": 0.26, "reverseHolofoil": 0.69}
    assert svc.backup.calls == []
    assert p.variant() == ("normal", 0.26)
    assert p.variant("reverseHolofoil") == ("reverseHolofoil", 0.69)
    assert p.variant("holofoil") == ("holofoil", None)


def test_backup_when_tcgdex_has_no_price(svc):
    p = svc.lookup("sv03.5-006")
    assert p.status == "ok" and p.provider == "pokemontcg" and p.prices == {"holofoil": 5.0}
    assert svc.backup.calls == ["sv3pt5-6"]  # TCGdex id mapped to pokemontcg.io's


def test_backup_when_tcgdex_is_down(svc):
    svc.primary.down = True
    p = svc.lookup("sv03.5-004")
    assert p.status == "ok" and p.provider == "pokemontcg" and p.prices == {"normal": 0.30}


def test_same_day_lookup_uses_cache(svc):
    svc.lookup("sv03.5-004")
    svc.primary.down = svc.backup.down = True
    p = svc.lookup("sv03.5-004")
    assert p.status == "ok" and not p.stale and p.provider == "tcgdex" and svc.primary.calls == ["sv03.5-004"]


def test_next_day_both_down_uses_old_price_marked_stale(svc):
    svc.lookup("sv03.5-004")
    svc.day["d"] = date(2026, 10, 15)
    svc.primary.down = svc.backup.down = True
    p = svc.lookup("sv03.5-004")
    assert p.status == "ok" and p.stale and p.fetched_on == "2026-10-14" and p.provider == "tcgdex"


def test_both_down_and_never_cached_is_unavailable(svc):
    svc.primary.down = svc.backup.down = True
    assert svc.lookup("sv03.5-004").status == "unavailable"


def test_no_price_anywhere_is_cached_for_the_day(svc):
    assert svc.lookup("sv03.5-005").status == "no_price"
    assert svc.lookup("sv03.5-005").status == "no_price"
    assert svc.primary.calls == ["sv03.5-005"] and svc.backup.calls == ["sv3pt5-5"]


def test_no_price_is_not_cached_when_a_provider_was_down(svc):
    svc.backup.down = True
    assert svc.lookup("sv03.5-005").status == "unavailable"
    svc.backup.down = False
    svc.backup.quotes["sv3pt5-5"] = TcgplayerQuote("sv3pt5-5", {"normal": 1.0}, "2026-10-14", None)
    assert svc.lookup("sv03.5-005").status == "ok"  # tried again, not stuck on "no price"


def test_unmapped_set_skips_the_backup(svc):
    assert svc.lookup("zzz-001").status == "no_price"
    assert svc.backup.calls == []


def test_old_database_gets_the_provider_column(tmp_path):
    import sqlite3

    path = tmp_path / "old.sqlite"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE price_cache (card_id TEXT, variant TEXT, market_usd REAL, price_date TEXT,"
                 " fetched_on TEXT, PRIMARY KEY (card_id, variant, fetched_on))")
    conn.commit()
    conn.close()
    cols = {r[1] for r in Store(path).conn.execute("PRAGMA table_info(price_cache)")}
    assert "provider" in cols
