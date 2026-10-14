"""What every price provider returns: TCGplayer market prices per variant, or an error
saying the provider couldn't be reached."""

from __future__ import annotations

from dataclasses import dataclass


class PriceUnavailable(Exception):
    """The price API couldn't be reached or kept failing (offline, 5xx, rate limit)."""


@dataclass
class TcgplayerQuote:
    card_id: str  # id in the provider's catalog
    # Market price in USD per variant: normal, holofoil, reverseHolofoil, 1stEditionHolofoil, ...
    prices: dict[str, float]
    # Date TCGplayer's prices were last updated at the provider (YYYY-MM-DD).
    updated_at: str | None
    url: str | None
