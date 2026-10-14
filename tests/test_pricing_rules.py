import pytest
from pydantic import ValidationError

from scanner.config import load_rules
from scanner.pricing.rules import CONDITIONS, PricingRules, pricing_rules


def test_config_file_is_valid():
    r = pricing_rules()
    assert set(r.condition_factors) == set(CONDITIONS)
    assert r.default_condition == "NM"


def _rules(**changes):
    data = dict(load_rules()["pricing"])
    data.update(changes)
    return PricingRules(**data)


@pytest.mark.parametrize("changes", [
    {"cash_pct": 1.5},
    {"credit_pct": 0},
    {"condition_factors": {"NM": 1.0, "LP": 0.8}},
    {"condition_factors": {"NM": 1.2, "LP": 0.8, "MP": 0.7, "HP": 0.5, "DMG": 0.3}},
    {"min_offer": {"mxn": -1, "usd": 0.5}},
    {"min_offer": {"mxn": 10}},
    {"default_condition": "MINT"},
])
def test_bad_rules_are_rejected(changes):
    with pytest.raises(ValidationError):
        _rules(**changes)
