"""Market price lookup from an ordered list of price APIs, with a daily SQLite cache
so the counter keeps working offline with every card already looked up."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Callable, Protocol

from server.config.rules import pricing_rules
from server.pricing.setmap import build_set_map, ptcg_card_id
from server.pricing.pokemontcg import PokemonTcgClient
from server.pricing.quote import PriceUnavailable, TcgplayerQuote

# Both providers publish TCGplayer's market price; this is what the offer cites.
SOURCE = "tcgplayer"


class PriceProvider(Protocol):
    name: str

    def quote(self, card_id: str) -> TcgplayerQuote | None:
        """Prices for a TCGdex card id; None if none. Raises PriceUnavailable."""


class TcgdexProvider:
    name = "tcgdex"

    def __init__(self, client):
        self.client = client

    def quote(self, card_id: str) -> TcgplayerQuote | None:
        return self.client.quote(card_id)


class PokemonTcgProvider:
    """pokemontcg.io, reached through a TCGdex -> pokemontcg.io set mapping."""

    name = "pokemontcg"

    def __init__(self, client: PokemonTcgClient, catalog_rows: dict[str, dict], tcgdex_sets: dict[str, dict],
                 ptcg_sets_path: Path):
        self.client = client
        self.rows = catalog_rows
        self.tcgdex_sets = tcgdex_sets
        self.ptcg_sets_path = ptcg_sets_path
        self._set_map: dict[str, str] | None = None

    @property
    def set_map(self) -> dict[str, str]:
        if self._set_map is None:
            if self.ptcg_sets_path.exists():
                ptcg = json.loads(self.ptcg_sets_path.read_text())
            else:
                ptcg = self.client.sets()  # once; new sets need the file deleted
                self.ptcg_sets_path.parent.mkdir(parents=True, exist_ok=True)
                self.ptcg_sets_path.write_text(json.dumps(ptcg))
            self._set_map = build_set_map(self.tcgdex_sets, ptcg)
        return self._set_map

    def quote(self, card_id: str) -> TcgplayerQuote | None:
        row = self.rows.get(card_id)
        ptcg_set = self.set_map.get(row["set"]) if row else None
        if not ptcg_set:
            return None
        return self.client.quote(ptcg_card_id(ptcg_set, row["number"]))


@dataclass
class PriceLookup:
    card_id: str
    # "ok": prices found · "no_price": no provider has a price for the card
    # · "unavailable": a provider couldn't be reached and nothing is cached.
    status: str
    prices: dict[str, float] = field(default_factory=dict)  # USD market price per variant
    source: str = SOURCE
    provider: str | None = None  # API the price came from
    price_date: str | None = None  # TCGplayer's update date
    fetched_on: str | None = None  # day we looked it up
    stale: bool = False  # from an older day's cache because the providers were down

    def variant(self, wanted: str | None = None) -> tuple[str | None, float | None]:
        """The requested variant's price, or the first variant in reglas.yaml's order."""
        if wanted:
            return (wanted, self.prices[wanted]) if wanted in self.prices else (wanted, None)
        for v in pricing_rules().variant_order:
            if v in self.prices:
                return v, self.prices[v]
        if self.prices:
            v = sorted(self.prices)[0]
            return v, self.prices[v]
        return None, None


class PriceService:
    def __init__(self, conn: sqlite3.Connection, providers: list[PriceProvider],
                 today: Callable[[], date] = date.today):
        self.conn = conn
        self.providers = providers
        self.today = today

    def lookup(self, card_id: str) -> PriceLookup:
        today = self.today()
        fresh_since = (today - timedelta(days=pricing_rules().price_cache_days - 1)).isoformat()
        cached = self._cached(card_id, since=fresh_since)
        if cached:
            return cached
        day = today.isoformat()
        unreachable = False
        for provider in self.providers:
            try:
                quote = provider.quote(card_id)
            except PriceUnavailable:
                unreachable = True
                continue
            if quote is not None:
                self.conn.executemany(
                    "INSERT OR REPLACE INTO price_cache (card_id, variant, market_usd, price_date, fetched_on,"
                    " provider) VALUES (?, ?, ?, ?, ?, ?)",
                    [(card_id, v, p, quote.updated_at, day, provider.name) for v, p in quote.prices.items()],
                )
                self.conn.commit()
                return PriceLookup(card_id, "ok", dict(quote.prices), provider=provider.name,
                                   price_date=quote.updated_at, fetched_on=day)
        if unreachable:
            # Don't cache "no price" when a provider might have had one.
            return self._cached(card_id, stale=True) or PriceLookup(card_id, "unavailable")
        self.conn.execute("INSERT OR REPLACE INTO price_cache (card_id, variant, market_usd, price_date, fetched_on)"
                          " VALUES (?, '', NULL, NULL, ?)", (card_id, day))
        self.conn.commit()
        return PriceLookup(card_id, "no_price", fetched_on=day)

    def _cached(self, card_id: str, since: str | None = None, stale: bool = False) -> PriceLookup | None:
        """Most recent cached lookup for the card (on or after `since` when given)."""
        q = "SELECT MAX(fetched_on) FROM price_cache WHERE card_id = ?"
        args: list = [card_id]
        if since:
            q += " AND fetched_on >= ?"
            args.append(since)
        day = self.conn.execute(q, args).fetchone()[0]
        if day is None:
            return None
        rows = self.conn.execute(
            "SELECT variant, market_usd, price_date, provider FROM price_cache WHERE card_id = ? AND fetched_on = ?",
            (card_id, day),
        ).fetchall()
        prices = {r[0]: r[1] for r in rows if r[0]}
        if not prices:
            return PriceLookup(card_id, "no_price", fetched_on=day, stale=stale)
        priced = next(r for r in rows if r[0])
        return PriceLookup(card_id, "ok", prices, provider=priced[3], price_date=priced[2], fetched_on=day,
                           stale=stale)


def build_providers(names: list[str], catalog_rows: dict[str, dict], tcgdex_sets: dict[str, dict],
                    ptcg_sets_path: Path, pokemontcg_api_key: str | None = None) -> list[PriceProvider]:
    """Providers in reglas.yaml's price_sources order."""
    from server.pricing.tcgdex import TcgdexPriceClient

    made: dict[str, Callable[[], PriceProvider]] = {
        "tcgdex": lambda: TcgdexProvider(TcgdexPriceClient()),
        "pokemontcg": lambda: PokemonTcgProvider(PokemonTcgClient(pokemontcg_api_key), catalog_rows,
                                                 tcgdex_sets, ptcg_sets_path),
    }
    return [made[n]() for n in names]
