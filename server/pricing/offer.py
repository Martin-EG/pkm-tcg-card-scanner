"""Offer per card: price_usd * (fx if CONVERT_TO_MXN) * condition factor * cash/credit share.

Every percentage, factor, and minimum comes from config/reglas.yaml (PricingRules).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from server.config.rules import PricingRules


@dataclass(frozen=True)
class Offer:
    currency: str  # "MXN" or "USD"
    market: float  # price in the offer currency, before condition and share
    cash: float
    credit: float
    buying: bool  # False: cash offer below the minimum ("no se compra")


def _money(value: Decimal, decimals: int) -> float:
    return float(value.quantize(Decimal(1).scaleb(-decimals), rounding=ROUND_HALF_UP))


def compute_offer(price_usd: float, condition: str, rules: PricingRules, fx_rate: float | None = None) -> Offer:
    """fx_rate given -> offer in MXN; None -> offer in USD."""
    if condition not in rules.condition_factors:
        raise ValueError(f"unknown condition {condition!r}")
    if price_usd < 0:
        raise ValueError("price can't be negative")
    market = Decimal(str(price_usd)) * (Decimal(str(fx_rate)) if fx_rate is not None else 1)
    adjusted = market * Decimal(str(rules.condition_factors[condition]))
    cash = _money(adjusted * Decimal(str(rules.cash_pct)), rules.decimals)
    credit = _money(adjusted * Decimal(str(rules.credit_pct)), rules.decimals)
    currency = "MXN" if fx_rate is not None else "USD"
    minimum = rules.min_offer[currency.lower()]
    return Offer(currency, _money(market, rules.decimals), cash, credit, buying=cash >= minimum)
