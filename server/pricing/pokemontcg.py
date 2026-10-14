"""pokemontcg.io client (backup price source): TCGplayer market price (USD) per card variant."""

from __future__ import annotations

import time

import httpx

from server.pricing.quote import PriceUnavailable, TcgplayerQuote

API = "https://api.pokemontcg.io/v2"


class PokemonTcgClient:
    def __init__(self, api_key: str | None = None, transport: httpx.BaseTransport | None = None,
                 timeout: float = 15.0, attempts: int = 3, backoff: float = 1.0):
        headers = {"X-Api-Key": api_key} if api_key else {}
        self.http = httpx.Client(base_url=API, headers=headers, timeout=timeout, transport=transport)
        self.attempts = attempts
        self.backoff = backoff

    def _get(self, path: str, params: dict | None = None) -> httpx.Response:
        last: Exception | None = None
        for attempt in range(self.attempts):
            try:
                r = self.http.get(path, params=params)
            except httpx.HTTPError as e:
                last = e
            else:
                if r.status_code == 429 or r.status_code >= 500:
                    last = PriceUnavailable(f"pokemontcg.io {r.status_code}")
                else:
                    return r
            if attempt < self.attempts - 1:
                time.sleep(self.backoff * 2 ** attempt)
        raise PriceUnavailable(str(last)) from last

    def sets(self) -> list[dict]:
        out, page = [], 1
        while True:
            r = self._get("/sets", {"page": page, "pageSize": 250,
                                    "select": "id,name,series,ptcgoCode,printedTotal,total,releaseDate"})
            r.raise_for_status()
            body = r.json()
            out += body["data"]
            if len(out) >= body.get("totalCount", 0) or not body["data"]:
                return out
            page += 1

    def quote(self, ptcg_id: str) -> TcgplayerQuote | None:
        """Market prices for one card, or None if pokemontcg.io doesn't know the card or
        has no TCGplayer price for it. Raises PriceUnavailable when the API can't be reached."""
        r = self._get(f"/cards/{ptcg_id}", {"select": "id,tcgplayer"})
        if r.status_code == 404:
            return None
        r.raise_for_status()
        tcg = (r.json().get("data") or {}).get("tcgplayer") or {}
        prices = {variant: float(p["market"]) for variant, p in (tcg.get("prices") or {}).items()
                  if p and p.get("market") is not None}
        if not prices:
            return None
        updated = tcg.get("updatedAt")
        return TcgplayerQuote(ptcg_id, prices, updated.replace("/", "-") if updated else None, tcg.get("url"))
