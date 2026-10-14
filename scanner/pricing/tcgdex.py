"""TCGdex price client: the TCGplayer market price (USD) per variant, as TCGdex
publishes it on each card. Same card ids as our catalog, so no set mapping."""

from __future__ import annotations

import time

import httpx

from scanner.pricing.tcgplayer import PriceUnavailable, TcgplayerQuote

API = "https://api.tcgdex.net/v2"
# TCGdex writes variants in kebab case; prices are stored under pokemontcg.io's
# camel-case names so reglas.yaml's variant_order covers both sources.
_VARIANTS = {
    "normal": "normal",
    "holofoil": "holofoil",
    "reverse-holofoil": "reverseHolofoil",
    "1st-edition": "1stEditionNormal",
    "1st-edition-holofoil": "1stEditionHolofoil",
    "unlimited": "unlimitedNormal",
    "unlimited-holofoil": "unlimitedHolofoil",
}


def _variant_name(key: str) -> str:
    if key in _VARIANTS:
        return _VARIANTS[key]
    head, *rest = key.split("-")
    return head + "".join(w.capitalize() for w in rest)


class TcgdexPriceClient:
    source = "tcgdex"

    def __init__(self, lang: str = "en", transport: httpx.BaseTransport | None = None,
                 timeout: float = 15.0, attempts: int = 3, backoff: float = 1.0):
        self.lang = lang
        self.http = httpx.Client(base_url=API, timeout=timeout, transport=transport)
        self.attempts = attempts
        self.backoff = backoff

    def quote(self, card_id: str) -> TcgplayerQuote | None:
        """TCGplayer market prices for a TCGdex card id, or None if TCGdex doesn't know
        the card or has no TCGplayer price for it. Raises PriceUnavailable when unreachable."""
        last: Exception | None = None
        for attempt in range(self.attempts):
            try:
                r = self.http.get(f"/{self.lang}/cards/{card_id}")
            except httpx.HTTPError as e:
                last = e
            else:
                if r.status_code == 404:
                    return None
                if r.status_code == 429 or r.status_code >= 500:
                    last = PriceUnavailable(f"tcgdex {r.status_code}")
                else:
                    r.raise_for_status()
                    return self._parse(card_id, r.json())
            if attempt < self.attempts - 1:
                time.sleep(self.backoff * 2 ** attempt)
        raise PriceUnavailable(str(last)) from last

    @staticmethod
    def _parse(card_id: str, card: dict) -> TcgplayerQuote | None:
        tcg = (card.get("pricing") or {}).get("tcgplayer") or {}
        if tcg.get("unit", "USD") != "USD":
            return None
        prices = {_variant_name(k): float(v["marketPrice"]) for k, v in tcg.items()
                  if isinstance(v, dict) and v.get("marketPrice") is not None}
        if not prices:
            return None
        updated = tcg.get("updated")
        return TcgplayerQuote(card_id, prices, updated[:10] if updated else None, None)
