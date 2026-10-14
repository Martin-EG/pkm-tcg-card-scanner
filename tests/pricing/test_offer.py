"""Offer math. The MVP example: US$10, FX 18.50, NM factor 1.0."""

import re
from pathlib import Path

import pytest

from server.config.rules import load_rules
from server.pricing.offer import compute_offer
from server.config.rules import PricingRules, pricing_rules


@pytest.fixture
def rules():
    """The real rules with the factors the example assumes (NM 1.0)."""
    data = dict(load_rules()["pricing"])
    data["condition_factors"] = {**data["condition_factors"], "NM": 1.0}
    return PricingRules(**data)


def test_mvp_example_in_pesos(rules):
    o = compute_offer(10.0, "NM", rules, fx_rate=18.50)
    assert (o.currency, o.market, o.cash, o.credit, o.buying) == ("MXN", 185.0, 157.25, 166.50, True)


def test_mvp_example_in_dollars(rules):
    o = compute_offer(10.0, "NM", rules)
    assert (o.currency, o.market, o.cash, o.credit) == ("USD", 10.0, 8.50, 9.00)


@pytest.mark.parametrize("condition", ["NM", "LP", "MP", "HP", "DMG"])
def test_each_condition_applies_its_factor(rules, condition):
    from decimal import ROUND_HALF_UP, Decimal

    def money(x):
        return float(x.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))

    f = Decimal(str(rules.condition_factors[condition]))
    o = compute_offer(20.0, condition, rules, fx_rate=18.0)
    assert o.cash == money(Decimal(360) * f * Decimal(str(rules.cash_pct)))
    assert o.credit == money(Decimal(360) * f * Decimal(str(rules.credit_pct)))


def test_conditions_rank_in_order(rules):
    cash = [compute_offer(20.0, c, rules).cash for c in ("NM", "LP", "MP", "HP", "DMG")]
    assert cash == sorted(cash, reverse=True)


def test_card_below_minimum_is_not_bought(rules):
    low = rules.min_offer["mxn"] / 18.5 / rules.cash_pct * 0.99  # cash offer just under the minimum
    assert not compute_offer(low, "NM", rules, fx_rate=18.5).buying
    assert compute_offer(low * 1.03, "NM", rules, fx_rate=18.5).buying
    assert not compute_offer(0.10, "NM", rules).buying  # USD minimum applies without conversion


def test_rounding_is_half_up(rules):
    # 1.03 * 0.85 = 0.8755 -> 0.88 (float math alone would give 0.87)
    assert compute_offer(1.03, "NM", rules).cash == 0.88


def test_unknown_condition(rules):
    with pytest.raises(ValueError):
        compute_offer(10.0, "MINT", rules)


def test_no_business_numbers_hardcoded_outside_config():
    """No percentage, factor, or minimum literal in the pricing code."""
    root = Path(__file__).resolve().parents[2]
    files = [root / "server" / "sessions" / "service.py", *sorted((root / "server" / "pricing").glob("*.py"))]
    assert len(files) >= 8, "pricing code moved; update this list"
    rules = pricing_rules()
    literals = {str(v) for v in (rules.cash_pct, rules.credit_pct, *rules.condition_factors.values(),
                                 *rules.min_offer.values())} - {"1.0"}
    for f in files:
        assert f.exists(), f
        code = "\n".join(line.split("#")[0] for line in f.read_text().splitlines())
        for lit in literals:
            assert not re.search(rf"(?<![\d.]){re.escape(lit)}(?![\d])", code), f"{lit} hardcoded in {f.name}"
