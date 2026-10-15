"""Buy sessions: the cards a customer brings, each with its price and offer, and the
session totals. Every offer stores the price, its source and date, and the exchange
rate it used (none when CONVERT_TO_MXN is false)."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timezone

from server.pricing.offer import compute_offer
from server.pricing.ebay import sold_search_url
from server.pricing.fx import FxService
from server.pricing.prices import PriceService
from server.config.rules import CONDITIONS, PricingRules


class SessionError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


@dataclass
class CardInput:
    card_id: str
    catalog_language: str = "en"
    printed_language: str | None = None  # OCR-detected language when not English
    scan_id: int | None = None
    card_index: int | None = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class SessionService:
    def __init__(self, conn: sqlite3.Connection, prices: PriceService, fx: FxService | None,
                 rules: PricingRules, catalog_rows: dict[str, dict], today=date.today):
        self.conn = conn
        self.prices = prices
        self.fx = fx  # None when CONVERT_TO_MXN is false
        self.rules = rules
        self.rows = catalog_rows
        self.today = today

    # --- sessions ------------------------------------------------------------------

    def create(self) -> dict:
        if self.fx is None:
            cur = self.conn.execute("INSERT INTO buy_sessions (created_at, currency) VALUES (?, 'USD')", (_now(),))
        else:
            rate = self.fx.current()  # FxUnavailable propagates: no offer in pesos without a rate
            cur = self.conn.execute(
                "INSERT INTO buy_sessions (created_at, currency, fx_rate, fx_date, fx_series, fx_stale)"
                " VALUES (?, 'MXN', ?, ?, ?, ?)", (_now(), rate.rate, rate.rate_date, rate.series, int(rate.stale)))
        self.conn.commit()
        return self.get(int(cur.lastrowid))

    def _session(self, session_id: int) -> sqlite3.Row:
        s = self.conn.execute("SELECT * FROM buy_sessions WHERE id = ?", (session_id,)).fetchone()
        if s is None:
            raise SessionError(404, "No existe esa sesión.")
        return s

    def get(self, session_id: int) -> dict:
        s = self._session(session_id)
        cards = [self._card_dict(r) for r in self.conn.execute(
            "SELECT * FROM session_cards WHERE session_id = ? AND removed_at IS NULL ORDER BY id", (session_id,))]
        counted = [c for c in cards if c["buying"] and c["accepted"]]
        d = self.rules.decimals
        return {
            "id": s["id"], "created_at": s["created_at"], "currency": s["currency"],
            "fx": None if s["fx_rate"] is None else {"rate": s["fx_rate"], "date": s["fx_date"],
                                                     "series": s["fx_series"], "stale": bool(s["fx_stale"])},
            "cards": cards,
            "totals": {
                "cash": round(sum(c["cash_offer"] for c in counted), d),
                "credit": round(sum(c["credit_offer"] for c in counted), d),
                "cards_buying": len(counted),
                "cards_not_buying": sum(1 for c in cards if c["buying"] is False),
                "cards_without_price": sum(1 for c in cards if c["buying"] is None),
            },
        }

    # --- cards ---------------------------------------------------------------------

    def add_card(self, session_id: int, card: CardInput) -> dict:
        s = self._session(session_id)
        row = self.rows.get(card.card_id)
        if row is None:
            raise SessionError(422, "La carta indicada no está en el catálogo.")
        printed = card.printed_language or card.catalog_language
        now = _now()
        cur = self.conn.execute(
            "INSERT INTO session_cards (session_id, scan_id, card_index, card_id, catalog_language,"
            " printed_language, name, set_name, number, condition, currency, ebay_url, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (session_id, card.scan_id, card.card_index, card.card_id, card.catalog_language, printed,
             row["name"], row["set_name"], row["number"], self.rules.default_condition, s["currency"],
             sold_search_url(row["name"], row["set_name"], row["number"], printed), now, now))
        self.conn.commit()
        return self._reprice(int(cur.lastrowid))

    def _card_row(self, session_id: int, card_row_id: int) -> sqlite3.Row:
        self._session(session_id)
        r = self.conn.execute("SELECT * FROM session_cards WHERE id = ? AND session_id = ?",
                              (card_row_id, session_id)).fetchone()
        if r is None:
            raise SessionError(404, "No existe esa carta en la sesión.")
        return r

    def remove_card(self, session_id: int, card_row_id: int) -> dict:
        """Take a card out of the session and its totals. The row stays, marked with the
        time it was removed, so mistaken scans can be reviewed later. Idempotent."""
        r = self._card_row(session_id, card_row_id)
        if r["removed_at"] is None:
            self.conn.execute("UPDATE session_cards SET removed_at = ?, updated_at = ? WHERE id = ?",
                              (_now(), _now(), card_row_id))
            self.conn.commit()
        return self.get(session_id)

    def restore_card(self, session_id: int, card_row_id: int) -> dict:
        """Undo remove_card. Idempotent."""
        self._card_row(session_id, card_row_id)
        self.conn.execute("UPDATE session_cards SET removed_at = NULL, updated_at = ? WHERE id = ?",
                          (_now(), card_row_id))
        self.conn.commit()
        return self.get(session_id)

    def update_card(self, session_id: int, card_row_id: int, changes: dict) -> dict:
        r = self._card_row(session_id, card_row_id)
        if r["removed_at"] is not None:
            raise SessionError(404, "Esa carta se quitó de la compra.")
        sets, args = [], []
        if "condition" in changes:
            if changes["condition"] not in CONDITIONS:
                raise SessionError(422, f"Condición no válida; usa una de {', '.join(CONDITIONS)}.")
            sets.append("condition = ?"); args.append(changes["condition"])
        if "variant" in changes:
            sets.append("variant = ?"); args.append(changes["variant"])
        if "accepted" in changes:
            sets.append("accepted = ?"); args.append(int(bool(changes["accepted"])))
        if "manual_price_usd" in changes:
            price = changes["manual_price_usd"]
            if price is None:  # back to the automatic price
                sets.append("price_manual = 0")
            else:
                if price < 0:
                    raise SessionError(422, "El precio no puede ser negativo.")
                sets += ["price_manual = 1", "price_usd = ?", "price_source = 'manual'", "price_provider = NULL",
                         "price_date = ?",
                         "price_approximate = 0", "price_stale = 0"]
                args += [float(price), self.today().isoformat()]
        if sets:
            sets.append("updated_at = ?"); args.append(_now())
            self.conn.execute(f"UPDATE session_cards SET {', '.join(sets)} WHERE id = ?", (*args, card_row_id))
            self.conn.commit()
        return self._reprice(card_row_id)

    def _reprice(self, card_row_id: int) -> dict:
        r = self.conn.execute("SELECT * FROM session_cards WHERE id = ?", (card_row_id,)).fetchone()
        s = self._session(r["session_id"])
        price_cols: dict = {}
        if not r["price_manual"]:
            price_cols = self._automatic_price(r)
        price = price_cols.get("price_usd", r["price_usd"]) if not r["price_manual"] else r["price_usd"]
        if price is None:
            offer_cols = {"market": None, "cash_offer": None, "credit_offer": None, "buying": None,
                          "fx_rate": None, "fx_date": None}
        else:
            o = compute_offer(price, r["condition"], self.rules, s["fx_rate"])
            offer_cols = {"market": o.market, "cash_offer": o.cash, "credit_offer": o.credit,
                          "buying": int(o.buying), "fx_rate": s["fx_rate"], "fx_date": s["fx_date"]}
        cols = {**price_cols, **offer_cols}
        self.conn.execute(f"UPDATE session_cards SET {', '.join(f'{k} = ?' for k in cols)} WHERE id = ?",
                          (*cols.values(), card_row_id))
        self.conn.commit()
        return self._card_dict(self.conn.execute("SELECT * FROM session_cards WHERE id = ?",
                                                 (card_row_id,)).fetchone())

    def _automatic_price(self, r: sqlite3.Row) -> dict:
        none = {"price_usd": None, "price_source": None, "price_provider": None, "price_date": None,
                "price_approximate": 0,
                "price_stale": 0, "variant": r["variant"], "variants": "[]"}
        if r["printed_language"] == "ja":
            return none  # Japanese prints sell differently: eBay or manual entry only
        lookup = self.prices.lookup(r["card_id"])
        if lookup.status != "ok":
            return none
        variant, price = lookup.variant(r["variant"])
        variants = json.dumps(sorted(lookup.prices))
        if price is None:
            return {**none, "variant": variant, "variants": variants}
        return {"price_usd": price, "price_source": lookup.source, "price_provider": lookup.provider,
                "price_date": lookup.price_date,
                "price_approximate": int(r["printed_language"] == "es"), "price_stale": int(lookup.stale),
                "variant": variant, "variants": variants}

    def _card_dict(self, r: sqlite3.Row) -> dict:
        return {
            "id": r["id"], "card_id": r["card_id"], "name": r["name"], "set_name": r["set_name"],
            "number": r["number"], "catalog_language": r["catalog_language"],
            "printed_language": r["printed_language"], "scan_id": r["scan_id"], "card_index": r["card_index"],
            "condition": r["condition"], "variant": r["variant"], "variants": json.loads(r["variants"] or "[]"),
            "price": None if r["price_usd"] is None else {
                "usd": r["price_usd"], "source": r["price_source"], "provider": r["price_provider"],
                "date": r["price_date"],
                "manual": bool(r["price_manual"]), "approximate": bool(r["price_approximate"]),
                "stale": bool(r["price_stale"])},
            "fx": None if r["fx_rate"] is None else {"rate": r["fx_rate"], "date": r["fx_date"]},
            "currency": r["currency"], "market": r["market"],
            "cash_offer": r["cash_offer"], "credit_offer": r["credit_offer"],
            "buying": None if r["buying"] is None else bool(r["buying"]),
            "accepted": bool(r["accepted"]), "ebay_url": r["ebay_url"],
        }
