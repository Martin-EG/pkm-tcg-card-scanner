"""TCGdex price client on recorded card responses."""

from pathlib import Path

import httpx
import pytest

from scanner.pricing.tcgdex import TcgdexPriceClient
from scanner.pricing.tcgplayer import PriceUnavailable

FIX = Path(__file__).parent / "fixtures"


def _client(handler):
    return TcgdexPriceClient(transport=httpx.MockTransport(handler), backoff=0)


def _fixture(card_id):
    return lambda r: httpx.Response(200, text=(FIX / f"tcgdex_card_{card_id}.json").read_text())


def test_reads_market_price_per_variant_with_shared_names():
    seen = {}

    def handler(request):
        seen["path"] = request.url.path
        return _fixture("sv03.5-004")(request)

    q = _client(handler).quote("sv03.5-004")
    assert seen["path"] == "/v2/en/cards/sv03.5-004"
    assert set(q.prices) == {"normal", "reverseHolofoil"}  # "reverse-holofoil" renamed
    assert q.prices["normal"] > 0 and q.updated_at and len(q.updated_at) == 10


def test_old_card_with_reverse_holo():
    q = _client(_fixture("ex12-57")).quote("ex12-57")
    assert set(q.prices) == {"normal", "reverseHolofoil"}


def test_card_without_price_or_unknown_is_none():
    assert _client(_fixture("30th-081")).quote("30th-081") is None
    assert _client(lambda r: httpx.Response(404)).quote("zzz-999") is None


def test_server_errors_and_network_are_unavailable():
    with pytest.raises(PriceUnavailable):
        _client(lambda r: httpx.Response(503)).quote("sv03.5-004")

    def down(request):
        raise httpx.ConnectError("offline")

    with pytest.raises(PriceUnavailable):
        _client(down).quote("sv03.5-004")
