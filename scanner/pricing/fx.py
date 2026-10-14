"""Banxico SIE client: USD -> MXN FIX rate (series SF43718), latest published value.

Only used when CONVERT_TO_MXN is true. The rate is looked up at most every
fx.refresh_hours and stored with the date Banxico published it for, so the
customer sees which day's rate was used.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable

import httpx

API = "https://www.banxico.org.mx/SieAPIRest/service/v1"


class FxUnavailable(Exception):
    """No rate available: no token, Banxico unreachable, and nothing stored."""


@dataclass
class FxRate:
    rate: float  # pesos per US dollar
    rate_date: str  # YYYY-MM-DD the rate was published for
    series: str
    stale: bool = False  # Banxico unreachable; last stored rate used


class BanxicoClient:
    def __init__(self, token: str | None, transport: httpx.BaseTransport | None = None, timeout: float = 15.0):
        self.token = token
        self.http = httpx.Client(base_url=API, timeout=timeout, transport=transport)

    def latest(self, series: str) -> tuple[float, str]:
        """(rate, YYYY-MM-DD) of the most recent published value."""
        if not self.token:
            raise FxUnavailable("Falta BANXICO_TOKEN en .env para obtener el tipo de cambio.")
        try:
            r = self.http.get(f"/series/{series}/datos/oportuno", headers={"Bmx-Token": self.token})
            r.raise_for_status()
            datos = r.json()["bmx"]["series"][0]["datos"]
        except (httpx.HTTPError, KeyError, IndexError, ValueError) as e:
            raise FxUnavailable(f"Banxico no respondió: {e}") from e
        for d in reversed(datos):
            try:
                rate = float(d["dato"].replace(",", ""))
            except (ValueError, AttributeError):
                continue  # "N/E": not published that day
            day, month, year = d["fecha"].split("/")
            return rate, f"{year}-{month}-{day}"
        raise FxUnavailable("Banxico no tiene un valor publicado para la serie.")


class FxService:
    def __init__(self, conn: sqlite3.Connection, client: BanxicoClient, series: str, refresh_hours: float,
                 now: Callable[[], datetime] = lambda: datetime.now(timezone.utc)):
        self.conn = conn
        self.client = client
        self.series = series
        self.refresh = timedelta(hours=refresh_hours)
        self.now = now

    def _stored(self) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT rate, rate_date, fetched_at FROM fx_rates WHERE series = ? ORDER BY rate_date DESC, fetched_at DESC"
            " LIMIT 1", (self.series,)).fetchone()

    def current(self) -> FxRate:
        stored = self._stored()
        if stored and self.now() - datetime.fromisoformat(stored[2]) < self.refresh:
            return FxRate(stored[0], stored[1], self.series)
        try:
            rate, rate_date = self.client.latest(self.series)
        except FxUnavailable:
            if stored:
                return FxRate(stored[0], stored[1], self.series, stale=True)
            raise
        self.conn.execute("INSERT OR REPLACE INTO fx_rates VALUES (?, ?, ?, ?)",
                          (self.series, rate_date, rate, self.now().isoformat()))
        self.conn.commit()
        return FxRate(rate, rate_date, self.series)
