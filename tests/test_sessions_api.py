"""Buy sessions over HTTP: prices, exchange rate, offers, manual prices, and totals.
Price and Banxico APIs are fakes; the math uses config/reglas.yaml."""

import json
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from scanner.api import create_app
from scanner.db import Store
from scanner.pricing.fx import BanxicoClient, FxService
from scanner.pricing.prices import PriceService, TcgdexProvider
from scanner.pricing.rules import pricing_rules
from scanner.pricing.tcgplayer import PriceUnavailable, TcgplayerQuote
from scanner.sessions import SessionService
from scanner.settings import Settings

FIX = Path(__file__).parent / "fixtures"
ROWS = {
    "sv03.5-004": {"id": "sv03.5-004", "set": "sv03.5", "number": "004", "name": "Charmander", "set_name": "151"},
    "sv03.5-005": {"id": "sv03.5-005", "set": "sv03.5", "number": "005", "name": "Charmeleon", "set_name": "151"},
    "sv03.5-006": {"id": "sv03.5-006", "set": "sv03.5", "number": "006", "name": "Charizard ex", "set_name": "151"},
}
BANXICO = {"bmx": {"series": [{"idSerie": "SF43718", "datos": [{"fecha": "13/10/2026", "dato": "18.50"}]}]}}


class FakeTcgdexPrices:
    """TCGdex price client by TCGdex card id."""

    quotes = {
        "sv03.5-004": TcgplayerQuote("sv03.5-004", {"normal": 10.0, "reverseHolofoil": 12.0}, "2026-10-14", None),
        "sv03.5-005": TcgplayerQuote("sv03.5-005", {"normal": 0.10}, "2026-10-14", None),
        # sv03.5-006: no TCGplayer price
    }

    def quote(self, card_id):
        return self.quotes.get(card_id)


def money(x):
    """Half-up to cents, like the offer code (plain round() on floats can go down)."""
    return float(Decimal(str(x)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def make_client(tmp_path, convert=True, banxico_up=True):
    store = Store(tmp_path / "db.sqlite")
    prices = PriceService(store.conn, [TcgdexProvider(FakeTcgdexPrices())], today=lambda: date(2026, 10, 14))
    fx = None
    if convert:
        handler = (lambda r: httpx.Response(200, json=BANXICO)) if banxico_up else (lambda r: httpx.Response(503))
        fx = FxService(store.conn, BanxicoClient("t", transport=httpx.MockTransport(handler)), "SF43718", 12)
    sessions = SessionService(store.conn, prices, fx, pricing_rules(), ROWS, today=lambda: date(2026, 10, 14))
    settings = Settings(convert_to_mxn=convert, _env_file=None)
    app = create_app(identifier=SimpleNamespace(languages=("en",)), store=store, sessions=sessions,
                     settings=settings, scans_dir=tmp_path / "scans")
    c = TestClient(app)
    c.store = store
    c.app_state_sessions = sessions
    return c


@pytest.fixture
def api(tmp_path):
    with make_client(tmp_path) as c:
        yield c


def _session_with(api, card_id, **extra):
    sid = api.post("/sessions").json()["id"]
    card = api.post(f"/sessions/{sid}/cards", json={"card_id": card_id, **extra})
    assert card.status_code == 201, card.text
    return sid, card.json()


def test_mvp_example_with_conversion(api):
    assert pricing_rules().condition_factors["NM"] == 1.0
    sid, card = _session_with(api, "sv03.5-004")
    assert (card["currency"], card["market"], card["cash_offer"], card["credit_offer"]) == ("MXN", 185.0, 157.25, 166.50)
    assert card["price"] == {"usd": 10.0, "source": "tcgplayer", "provider": "tcgdex", "date": "2026-10-14",
                             "manual": False, "approximate": False, "stale": False}
    assert card["fx"] == {"rate": 18.5, "date": "2026-10-13"}
    assert card["variant"] == "normal" and card["variants"] == ["normal", "reverseHolofoil"]
    s = api.get(f"/sessions/{sid}").json()
    assert s["totals"]["cash"] == 157.25 and s["totals"]["credit"] == 166.50
    assert s["fx"]["rate"] == 18.5


def test_mvp_example_without_conversion(tmp_path):
    with make_client(tmp_path, convert=False) as api:
        sid, card = _session_with(api, "sv03.5-004")
        assert (card["currency"], card["cash_offer"], card["credit_offer"]) == ("USD", 8.50, 9.00)
        assert card["fx"] is None
        assert api.get(f"/sessions/{sid}").json()["fx"] is None
        row = api.store.conn.execute("SELECT fx_rate, fx_date FROM session_cards").fetchone()
        assert tuple(row) == (None, None)  # no rate stored when conversion is off
        assert api.get("/settings").json()["currency"] == "USD"


def test_every_offer_stores_price_source_date_and_rate(api):
    _session_with(api, "sv03.5-004")
    row = api.store.conn.execute(
        "SELECT price_usd, price_source, price_provider, price_date, fx_rate, fx_date, cash_offer"
        " FROM session_cards").fetchone()
    assert tuple(row) == (10.0, "tcgplayer", "tcgdex", "2026-10-14", 18.5, "2026-10-13", 157.25)


@pytest.mark.parametrize("condition", ["NM", "LP", "MP", "HP", "DMG"])
def test_each_condition(api, condition):
    sid, card = _session_with(api, "sv03.5-004")
    r = api.patch(f"/sessions/{sid}/cards/{card['id']}", json={"condition": condition}).json()
    f = pricing_rules().condition_factors[condition]
    assert r["condition"] == condition
    assert r["cash_offer"] == money(Decimal("185") * Decimal(str(f)) * Decimal(str(pricing_rules().cash_pct)))
    assert r["credit_offer"] == money(Decimal("185") * Decimal(str(f)) * Decimal(str(pricing_rules().credit_pct)))


def test_variant_change_reprices(api):
    sid, card = _session_with(api, "sv03.5-004")
    r = api.patch(f"/sessions/{sid}/cards/{card['id']}", json={"variant": "reverseHolofoil"}).json()
    assert r["price"]["usd"] == 12.0
    assert r["cash_offer"] == money(Decimal("222") * Decimal(str(pricing_rules().cash_pct)))


def test_card_below_minimum_is_not_bought(api):
    sid, card = _session_with(api, "sv03.5-005")  # US$0.10 -> 1.57 MXN cash, under the minimum
    assert card["buying"] is False
    s = api.get(f"/sessions/{sid}").json()
    assert s["totals"] == {"cash": 0, "credit": 0, "cards_buying": 0, "cards_not_buying": 1,
                           "cards_without_price": 0}


def test_card_without_price_then_manual_price(api):
    sid, card = _session_with(api, "sv03.5-006")
    assert card["price"] is None and card["buying"] is None and card["cash_offer"] is None
    assert card["ebay_url"].startswith("https://www.ebay.com/sch/i.html?")
    assert api.get(f"/sessions/{sid}").json()["totals"]["cards_without_price"] == 1
    r = api.patch(f"/sessions/{sid}/cards/{card['id']}", json={"manual_price_usd": 10}).json()
    assert r["price"]["manual"] is True and r["price"]["source"] == "manual" and r["price"]["provider"] is None
    assert r["cash_offer"] == 157.25
    s = api.get(f"/sessions/{sid}").json()
    assert s["cards"][0]["price"]["manual"] is True and s["totals"]["cash"] == 157.25


def test_manual_price_can_be_cleared(api):
    sid, card = _session_with(api, "sv03.5-004")
    api.patch(f"/sessions/{sid}/cards/{card['id']}", json={"manual_price_usd": 3})
    r = api.patch(f"/sessions/{sid}/cards/{card['id']}", json={"manual_price_usd": None}).json()
    assert r["price"]["manual"] is False and r["price"]["usd"] == 10.0


def test_spanish_card_uses_english_price_marked_approximate(api):
    _, card = _session_with(api, "sv03.5-004", printed_language="es")
    assert card["price"]["approximate"] is True and card["cash_offer"] == 157.25
    assert "Spanish" in card["ebay_url"]


def test_japanese_card_waits_for_manual_price(api):
    _, card = _session_with(api, "sv03.5-004", printed_language="ja")
    assert card["price"] is None and "Japanese" in card["ebay_url"]


def test_rejected_card_leaves_totals(api):
    sid, card = _session_with(api, "sv03.5-004")
    api.patch(f"/sessions/{sid}/cards/{card['id']}", json={"accepted": False})
    assert api.get(f"/sessions/{sid}").json()["totals"]["cash"] == 0


def test_totals_add_up_several_cards(api):
    sid, _ = _session_with(api, "sv03.5-004")
    api.post(f"/sessions/{sid}/cards", json={"card_id": "sv03.5-004"})
    api.post(f"/sessions/{sid}/cards", json={"card_id": "sv03.5-005"})
    t = api.get(f"/sessions/{sid}").json()["totals"]
    assert (t["cash"], t["credit"], t["cards_buying"], t["cards_not_buying"]) == (314.5, 333.0, 2, 1)


def test_errors(api):
    assert api.get("/sessions/999").status_code == 404
    sid = api.post("/sessions").json()["id"]
    assert api.post(f"/sessions/{sid}/cards", json={"card_id": "nope"}).status_code == 422
    assert api.patch(f"/sessions/{sid}/cards/999", json={}).status_code == 404
    other, card = _session_with(api, "sv03.5-004")
    # A card can only be changed through its own session.
    assert api.patch(f"/sessions/{sid}/cards/{card['id']}", json={"condition": "LP"}).status_code == 404


def test_bad_condition(api):
    sid, card = _session_with(api, "sv03.5-004")
    r = api.patch(f"/sessions/{sid}/cards/{card['id']}", json={"condition": "MINT"})
    assert r.status_code == 422


def test_no_exchange_rate_means_no_session(tmp_path):
    with make_client(tmp_path, banxico_up=False) as api:
        r = api.post("/sessions")
        assert r.status_code == 503 and r.json()["error"] == "fx_unavailable"


def test_settings(api):
    s = api.get("/settings").json()
    assert s["languages"] == ["en"] and s["currency"] == "MXN" and s["convert_to_mxn"] is True
    assert [c["code"] for c in s["conditions"]] == ["NM", "LP", "MP", "HP", "DMG"]
    assert s["min_offer"] == pricing_rules().min_offer["mxn"]


def test_price_api_down_without_cache_gives_no_price(tmp_path):
    with make_client(tmp_path) as api:
        class Down:
            def quote(self, ptcg_id):
                raise PriceUnavailable("offline")

        api.app_state_sessions.prices.providers = [Down()]
        _, card = _session_with(api, "sv03.5-004")
        assert card["price"] is None and card["buying"] is None
