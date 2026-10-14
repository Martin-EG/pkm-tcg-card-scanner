"""pokemontcg.io client and TCGdex -> pokemontcg.io set mapping, on recorded responses."""

import json
from pathlib import Path

import httpx
import pytest

from scanner.pricing.setmap import build_set_map, ptcg_card_id
from scanner.pricing.tcgplayer import PriceUnavailable, TcgplayerClient

FIX = Path(__file__).parent / "fixtures"


def test_set_map_on_real_set_lists():
    tcgdex = json.loads((FIX / "tcgdex_sets_sample.json").read_text())
    ptcg = json.loads((FIX / "ptcg_sets_sample.json").read_text())
    m = build_set_map(tcgdex, ptcg)
    assert m == {"base1": "base1", "sv03.5": "sv3pt5", "sv04.5": "sv4pt5", "svp": "svp",
                 "hgss3": "hgss3", "me01": "me1", "me04": "me4", "swshp": "swshp"}


@pytest.mark.parametrize("set_id,number,want", [
    ("sv3pt5", "004", "sv3pt5-4"), ("swsh9tg", "TG01", "swsh9tg-TG01"), ("swshp", "SWSH001", "swshp-SWSH001"),
])
def test_card_id(set_id, number, want):
    assert ptcg_card_id(set_id, number) == want


def _client(handler, **kw):
    return TcgplayerClient(transport=httpx.MockTransport(handler), backoff=0, **kw)


def test_quote_reads_market_price_per_variant():
    body = (FIX / "ptcg_card_sv3pt5-4.json").read_text()
    seen = {}

    def handler(request):
        seen["path"], seen["key"] = request.url.path, request.headers.get("X-Api-Key")
        return httpx.Response(200, text=body)

    q = _client(handler, api_key="k").quote("sv3pt5-4")
    assert seen == {"path": "/v2/cards/sv3pt5-4", "key": "k"}
    assert q.prices == {"reverseHolofoil": 0.69, "normal": 0.26}
    assert q.updated_at == "2026-10-14"


def test_unknown_card_or_no_price_is_none():
    assert _client(lambda r: httpx.Response(404, json={"error": "not found"})).quote("x-1") is None
    no_price = {"data": {"id": "x-1", "tcgplayer": {"prices": {"normal": {"market": None}}}}}
    assert _client(lambda r: httpx.Response(200, json=no_price)).quote("x-1") is None
    assert _client(lambda r: httpx.Response(200, json={"data": {"id": "x-1"}})).quote("x-1") is None


def test_retries_then_gives_up_on_server_errors():
    calls = []

    def flaky(request):
        calls.append(1)
        return httpx.Response(502) if len(calls) < 3 else httpx.Response(200, text=(FIX / "ptcg_card_sv3pt5-4.json").read_text())

    assert _client(flaky).quote("sv3pt5-4").prices["normal"] == 0.26
    with pytest.raises(PriceUnavailable):
        _client(lambda r: httpx.Response(502)).quote("sv3pt5-4")


def test_network_error_is_price_unavailable():
    def down(request):
        raise httpx.ConnectError("offline")

    with pytest.raises(PriceUnavailable):
        _client(down).quote("sv3pt5-4")
