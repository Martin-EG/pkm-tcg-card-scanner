# Phase 2 — Prices, exchange rate, and offer: results

Oct 14, 2026

## Verdict

Every [AUTO] gate item passes. The MVP example comes out exactly in both modes: 157.25 / 166.50 MXN and 8.50 / 9.00 USD. Every offer stores the price, its source and date, and the exchange rate used. Manual prices are flagged. No percentage, factor or minimum is written in the code.

**Price source: TCGdex first, pokemontcg.io as backup.** Both publish TCGplayer's market price. TCGdex uses the same card ids as our catalog and prices sets that pokemontcg.io doesn't yet. In the live check it priced **39 of 41** cards in 7 s. pokemontcg.io alone priced 19, gave errors on 9, and took 68 s.

## QA gate

| item | result | evidence |
|---|---|---|
| [AUTO] US$10, FX 18.50, NM 1.0 → 157.25 cash / 166.50 credit (MXN); 8.50 / 9.00 USD without conversion | **PASS** | `test_offer.py::test_mvp_example_in_pesos`, `…_in_dollars`; end to end over HTTP in `test_sessions_api.py::test_mvp_example_with_conversion`, `…_without_conversion` |
| [AUTO] Every offer stores price, source, date, and exchange rate (no rate when conversion is off) | **PASS** | `test_every_offer_stores_price_source_date_and_rate` reads the SQLite row: `(10.0, 'tcgplayer', '2026-10-14', 18.5, '2026-10-13', 157.25)`. `test_mvp_example_without_conversion`: `fx_rate`, `fx_date` = `NULL` |
| [AUTO] A manually entered price is flagged as manual | **PASS** | `test_card_without_price_then_manual_price`: `price.manual = true`, `source = "manual"`, in the card and in the session summary |
| [AUTO] Tests for each condition, a card below the minimum, a card without a price | **PASS** | `test_each_condition[NM…DMG]` (offer math and HTTP), `test_card_below_minimum_is_not_bought` (both), `test_card_without_price_then_manual_price` |
| [AUTO] No percentage, factor, or minimum hardcoded outside `config/` and `.env` | **PASS** | `test_no_business_numbers_hardcoded_outside_config` scans the pricing code for the values in `reglas.yaml`. A repo-wide search found two leftover crop thresholds (0.9, 0.6) in `crop.py`; they're now in `reglas.yaml` too |

Tests: 151 pass (`python -m pytest -q`). The price and Banxico clients are tested on recorded responses and never call the network.

### [MANUAL] for the owner

1. **Put a Banxico token in `.env`** (`BANXICO_TOKEN`). It's free at https://www.banxico.org.mx/SieAPIRest/service/v1/token. Without it, `POST /sessions` returns 503 `fx_unavailable` while `CONVERT_TO_MXN=true`. The live Banxico call isn't verified yet, since there's no token here.
2. **Set the real condition factors and minimum** with the shop in `config/reglas.yaml`. They're provisional and marked `TODO`: NM 1.0 · LP 0.85 · MP 0.70 · HP 0.50 · DMG 0.30; minimum $10.00 MXN / US$0.50, compared to the cash offer.
3. **Optional: a pokemontcg.io API key** (`POKEMONTCG_API_KEY`) for higher rate limits on the backup source.

## Live price check (the 41 Phase 0 cards)

| | pokemontcg.io only (first run) | TCGdex first, pokemontcg.io backup (now) |
|---|---|---|
| priced | 19 | **39**: 38 from TCGdex, 1 from the backup (`svp-173`, a promo TCGdex doesn't price) |
| no price | 13 (12 Chaos Rising, 1 30th Celebration) | 2, both 30th Celebration (released Sept 16, 2026; neither source prices it yet) |
| errors | 9 (`500`/`502` after 3 tries) | 0 |
| time for 41 cards | 67.6 s | 7.0 s (~0.09 s per card) |

Cached prices made the second run in a day instant. Those two cards fall back to the eBay link and a manual price.

For the backup, the TCGdex → pokemontcg.io set mapping covers 150 of 150 catalog sets:
- 147 are matched automatically: name + release date, then printed code + printed size.
- 3 use overrides: SVP promos, Undaunted, Triumphant.

## What was built

- **`scanner/pricing/tcgdex.py`**: main price source. Reads the TCGplayer market price (USD) per variant that TCGdex publishes on each card. It uses our own card ids, so no mapping. Variant names are converted to pokemontcg.io's (`reverse-holofoil` → `reverseHolofoil`).
- **`scanner/pricing/tcgplayer.py`**
  - The pokemontcg.io client (backup): TCGplayer market price (USD) per variant (normal, holofoil, reverseHolofoil, 1st edition…).
  - Returns `None` when a card is unknown or has no price.
  - Retries `429`/`5xx`, then raises `PriceUnavailable`.
- **`scanner/pricing/setmap.py`**: maps TCGdex set ids to pokemontcg.io set ids (`sv03.5` → `sv3pt5`), and builds card ids (`004` → `sv3pt5-4`).
- **`scanner/pricing/prices.py`**: price providers tried in the order `pricing.price_sources` sets (`[tcgdex, pokemontcg]`), plus a daily SQLite price cache (`price_cache`).
  - A card looked up today isn't fetched again. "No price" is remembered for the day, unless a provider was down, so the next request tries again.
  - When every provider is down, the last stored price is used, marked `stale`, with its date.
  - Each price records the provider that supplied it (`price.provider`: `tcgdex` | `pokemontcg`). The source stays `tcgplayer`, since both carry TCGplayer's market price.
- **`scanner/pricing/fx.py`**: Banxico SIE client for series SF43718.
  - Takes the latest published value and its date. Skips "N/E" days.
  - Stored in `fx_rates` and refreshed at most every 12 h (`fx.refresh_hours`).
  - Falls back to the stored rate, marked stale. Never called when `CONVERT_TO_MXN=false`.
- **`scanner/pricing/ebay.py`**: eBay sold-items search URL: name + set + number + language, Pokémon singles category. No scraping.
- **`scanner/offer.py`**
  - Formula: price × FX (if on) × condition factor × cash or credit share, rounded half-up to cents with `Decimal`.
  - `buying = cash offer ≥ minimum` for the active currency.
- **`scanner/sessions.py` + endpoints**
  - `POST /sessions`, `GET /sessions/{id}`, `POST /sessions/{id}/cards`, `PATCH /sessions/{id}/cards/{card_id}` (condition, variant, `manual_price_usd`, accepted) and `GET /settings`.
  - The exchange rate is fixed when a session opens, so all of a customer's cards use the same rate. Each card row stores the price, source, date, the manual and approximate flags, the rate, the offer and the eBay URL.
  - Totals count only cards that are being bought and accepted.
- **Language rules** (from the MVP doc):
  - A card flagged Spanish in Phase 1 gets the English price, marked `approximate`.
  - A Japanese card gets no automatic price; the employee uses eBay and a manual price.
- **Rules and settings**
  - `config/reglas.yaml` gains `pricing` (cash/credit shares, condition factors, minimum per currency, rounding, variant order, cache days) and `fx`. It's validated at startup (`scanner/pricing/rules.py`): a missing condition or a share above 1 stops the server.
  - `.env` gains `POKEMONTCG_API_KEY` and `BANXICO_TOKEN`.

## Decisions to know about

- **Manual prices are entered in US dollars**, as eBay shows them, then go through the same formula. The summary marks them manual.
- **The minimum compares against the cash offer**, after condition, as chosen by the owner.
- **No exchange rate means no new session.** With conversion on, a session won't open unless Banxico or a stored rate is available. The other option would be offers in pesos with no rate behind them.
- **Other price APIs considered:**
  - JustTCG and PokemonPriceTracker have per-condition and eBay sold prices, but their free tiers are non-commercial and a shop needs a paid plan.
  - PriceCharting is paid.
  - TCGplayer's own API is closed to new developers.
- **New pokemontcg.io sets:** the set list is cached in `data/cache/ptcg_sets.json`. When a new set comes out, delete that file so it's downloaded again.

## Next

Phase 3: the counter app (React + Vite PWA) on top of `/identify`, `/sessions` and `/settings`.
