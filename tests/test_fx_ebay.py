from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from scanner.db import Store
from scanner.pricing.ebay import sold_search_url
from scanner.pricing.fx import BanxicoClient, FxService, FxUnavailable

# Shape of a Banxico SIE "oportuno" response.
BANXICO = {"bmx": {"series": [{"idSerie": "SF43718", "titulo": "Tipo de cambio FIX",
                                "datos": [{"fecha": "13/10/2026", "dato": "18.5000"}]}]}}


def _client(handler, token="t"):
    return BanxicoClient(token, transport=httpx.MockTransport(handler))


def test_banxico_latest_value_and_token_header():
    seen = {}

    def handler(request):
        seen["path"], seen["token"] = request.url.path, request.headers.get("Bmx-Token")
        return httpx.Response(200, json=BANXICO)

    assert _client(handler).latest("SF43718") == (18.5, "2026-10-13")
    assert seen == {"path": "/SieAPIRest/service/v1/series/SF43718/datos/oportuno", "token": "t"}


def test_banxico_without_token_or_value():
    with pytest.raises(FxUnavailable):
        _client(lambda r: httpx.Response(200, json=BANXICO), token=None).latest("SF43718")
    ne = {"bmx": {"series": [{"datos": [{"fecha": "13/10/2026", "dato": "N/E"}]}]}}
    with pytest.raises(FxUnavailable):
        _client(lambda r: httpx.Response(200, json=ne)).latest("SF43718")
    with pytest.raises(FxUnavailable):
        _client(lambda r: httpx.Response(503)).latest("SF43718")


@pytest.fixture
def fx(tmp_path):
    state = {"now": datetime(2026, 10, 14, 15, tzinfo=timezone.utc), "calls": 0, "down": False}

    def handler(request):
        state["calls"] += 1
        return httpx.Response(503) if state["down"] else httpx.Response(200, json=BANXICO)

    svc = FxService(Store(tmp_path / "db.sqlite").conn, _client(handler), "SF43718", 12, now=lambda: state["now"])
    svc.state = state
    return svc


def test_rate_is_reused_until_refresh(fx):
    assert fx.current().rate == 18.5
    fx.state["now"] += timedelta(hours=6)
    assert fx.current().rate == 18.5 and fx.state["calls"] == 1
    fx.state["now"] += timedelta(hours=7)
    fx.current()
    assert fx.state["calls"] == 2


def test_banxico_down_uses_stored_rate_marked_stale(fx):
    fx.current()
    fx.state["now"] += timedelta(days=1)
    fx.state["down"] = True
    r = fx.current()
    assert (r.rate, r.rate_date, r.stale) == (18.5, "2026-10-13", True)


def test_banxico_down_and_nothing_stored(fx):
    fx.state["down"] = True
    with pytest.raises(FxUnavailable):
        fx.current()


def test_ebay_sold_search_url():
    url = sold_search_url("Charmander", "151", "004", "ja")
    q = parse_qs(urlparse(url).query)
    assert url.startswith("https://www.ebay.com/sch/i.html?")
    assert q["_nkw"] == ["Charmander 151 004 Japanese"]
    assert q["LH_Sold"] == ["1"] and q["LH_Complete"] == ["1"]
    assert parse_qs(urlparse(sold_search_url("Pikachu", "Base", "58")).query)["_nkw"] == ["Pikachu Base 58"]
