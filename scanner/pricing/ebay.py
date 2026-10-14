"""eBay sold-items search URL for a card. No scraping: the employee opens the
search, checks recent sales, and types the price."""

from __future__ import annotations

from urllib.parse import urlencode

SEARCH = "https://www.ebay.com/sch/i.html"
# eBay category: Pokémon TCG individual cards.
CATEGORY = "183454"
LANGUAGE_WORDS = {"en": "", "es": "Spanish", "ja": "Japanese"}


def sold_search_url(name: str, set_name: str, number: str, language: str = "en") -> str:
    query = " ".join(p for p in (name, set_name, number, LANGUAGE_WORDS.get(language, language)) if p)
    return f"{SEARCH}?{urlencode({'_nkw': query, '_sacat': CATEGORY, 'LH_Sold': 1, 'LH_Complete': 1})}"
