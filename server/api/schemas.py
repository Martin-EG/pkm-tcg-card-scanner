"""Request bodies accepted by the API."""

from __future__ import annotations

from pydantic import BaseModel


class Correction(BaseModel):
    scan_id: int
    card_index: int
    card_id: str
    language: str = "en"


class SessionCardIn(BaseModel):
    card_id: str
    catalog_language: str = "en"
    # detected_language from /identify when the card is printed in Spanish or Japanese.
    printed_language: str | None = None
    scan_id: int | None = None
    card_index: int | None = None


class SessionCardPatch(BaseModel):
    condition: str | None = None
    variant: str | None = None
    # US dollars, as eBay shows them; null goes back to the automatic price.
    manual_price_usd: float | None = None
    accepted: bool | None = None
