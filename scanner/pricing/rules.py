"""Pricing rules from config/reglas.yaml, validated at load time so a bad value
stops the server at startup instead of producing wrong offers."""

from __future__ import annotations

from functools import lru_cache

from pydantic import BaseModel, Field, field_validator, model_validator

from scanner.config import rules

CONDITIONS = ("NM", "LP", "MP", "HP", "DMG")


class PricingRules(BaseModel):
    cash_pct: float = Field(gt=0, le=1)
    credit_pct: float = Field(gt=0, le=1)
    condition_factors: dict[str, float]
    default_condition: str
    min_offer: dict[str, float]
    decimals: int = Field(ge=0, le=4)
    variant_order: list[str]
    price_sources: list[str] = Field(min_length=1)
    price_cache_days: int = Field(ge=1)

    @field_validator("price_sources")
    @classmethod
    def _sources(cls, v: list[str]) -> list[str]:
        unknown = set(v) - {"tcgdex", "pokemontcg"}
        if unknown:
            raise ValueError(f"unknown price sources {sorted(unknown)}; use tcgdex and/or pokemontcg")
        return v

    @field_validator("condition_factors")
    @classmethod
    def _factors(cls, v: dict[str, float]) -> dict[str, float]:
        if set(v) != set(CONDITIONS):
            raise ValueError(f"condition_factors must have exactly {CONDITIONS}, got {sorted(v)}")
        for k, f in v.items():
            if not 0 < f <= 1:
                raise ValueError(f"condition factor {k}={f} must be in (0, 1]")
        return v

    @field_validator("min_offer")
    @classmethod
    def _minimum(cls, v: dict[str, float]) -> dict[str, float]:
        if set(v) != {"mxn", "usd"} or any(x < 0 for x in v.values()):
            raise ValueError("min_offer needs non-negative mxn and usd values")
        return v

    @model_validator(mode="after")
    def _default(self) -> "PricingRules":
        if self.default_condition not in CONDITIONS:
            raise ValueError(f"default_condition must be one of {CONDITIONS}")
        return self


class FxRules(BaseModel):
    series: str
    refresh_hours: float = Field(gt=0)


@lru_cache
def pricing_rules() -> PricingRules:
    return PricingRules(**rules()["pricing"])


@lru_cache
def fx_rules() -> FxRules:
    return FxRules(**rules()["fx"])
