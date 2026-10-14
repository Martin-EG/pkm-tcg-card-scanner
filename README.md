# TCG Buylist Scanner

A Pokémon card scanner for small TCG shops in Mexicali, Mexico. An employee takes a photo of one card or a binder page with their phone. The shop's PC identifies each card, looks up its market price, and calculates the buy offer in cash and in store credit, using the shop's own rules.

Everything runs on the shop PC: open models, a local card index, and no cloud vision API. Customer photos never leave the shop. Only price and exchange-rate lookups use the internet, and both are cached so the counter keeps working offline.

## How it works

```
photo ─► crop ─► image search ─► OCR re-rank ─► card + confidence
         1–9      DINOv2 +        set code,
         cards    FAISS index     number, language
                                        │
card ─► price (TCGplayer market price via TCGdex, pokemontcg.io as backup; cached daily)
     ─► × exchange rate (Banxico FIX, optional)
     ─► × condition factor × 85% cash | 90% credit  ─►  offer + session total
```

1. **Crop:** finds 1 to 9 cards in the photo and straightens each one. Blurry photos and photos with no card get a clear error instead of a guess.
2. **Identify:** each card is embedded with DINOv2 and searched in a FAISS index of the full English TCGdex catalog (19,663 cards).
3. **Read:** PaddleOCR reads the set code and collector number to tell apart same-art reprints, and the name bar to flag Spanish and Japanese cards.
4. **Price and offer:**
   - **Price:** the TCGplayer market price, read from TCGdex, with pokemontcg.io as a backup.
   - **Exchange rate:** Banxico's FIX rate (series SF43718), used when converting to pesos.
   - **Offer:** `price_usd × FX × condition factor × cash or credit share`.
   - **Fallback:** cards without a price get an eBay sold-items link and a field for a manual price.

Every percentage, factor and minimum lives in `config/reglas.yaml`. None are written in the code.

## Status

| Phase | What | State |
|---|---|---|
| 0 | Identification proof of concept (image only) | done: [results](docs/phase0-results.md) |
| 1 | Identification service: multi-card crop, OCR, `POST /identify` | done: [results](docs/phase1-results.md) |
| 2 | Prices, exchange rate, offers, buy sessions | done: [results](docs/phase2-results.md) |
| 3 | Counter app (React + Vite PWA, Mexican Spanish UI) | next |
| 4 | Test at a shop | planned |

Spanish and Japanese catalogs are deferred for now. Cards printed in those languages are flagged for the employee to check.

## Project structure

```
config/reglas.yaml        Business rules and every tunable threshold (shares, factors, minimum, crop, OCR)
.env.example              Server settings: languages, USD→MXN conversion, API keys
scanner/
  api.py                  FastAPI app: /identify, /corrections, /sessions, /settings
  crop.py                 Card detection and perspective correction (1–9 cards per photo)
  embedders.py            DINOv2 / CLIP image embeddings (whole card + artwork box)
  index.py                FAISS index per model and language
  identify.py             Photo → cards: crop, embed, search, OCR re-rank, review flags
  ocr.py                  PaddleOCR reading and parsing of set code, number, language
  catalog.py              Catalog rows joined with set info (printed code, set size)
  offer.py                Offer formula
  sessions.py             Buy sessions: cards, prices, offers, totals
  pricing/                TCGdex and pokemontcg.io price clients, set mapping, daily price cache, Banxico, eBay link, rules
  db.py                   SQLite schema: scans, corrections, price cache, FX rates, sessions
  settings.py, config.py  .env and reglas.yaml loaders
scripts/
  fetch_catalog.py        Download the TCGdex catalog and card images (resumable)
  build_index.py          Embed the catalog into a FAISS index
  eval.py                 Phase 0 evaluation (image only)
  eval_phase1.py          Phase 1 QA gate (accuracy, page time, reprints, errors, languages)
  fix_macos_openmp.sh     macOS only: make faiss and torch share one OpenMP runtime
tests/                    pytest suite; network calls are faked or recorded
photos/                   Labeled test photos (<tcgdex id>.heic), binder pages, Spanish cards
docs/                     MVP, phase plan, per-phase results
reports/                  Evaluation output committed with each phase
data/                     Catalog, images, indexes, SQLite (git-ignored, ~2 GB)
```

## Getting started

Requires Python 3.11+ and about 3 GB of disk space. The shop PC needs no GPU.

### 1. Install

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu   # CPU build; skip on macOS
pip install -r requirements.txt
```

On macOS, run this once after installing:

```bash
scripts/fix_macos_openmp.sh
```

It's needed because torch and faiss each ship their own OpenMP library, and loading both crashes with `OMP: Error #15`.

### 2. Configure

```bash
cp .env.example .env
```

| Variable | Default | Meaning |
|---|---|---|
| `ENABLE_SPANISH` / `ENABLE_JAPANESE` | `false` | Search those catalogs (not built yet; cards are flagged instead) |
| `CONVERT_TO_MXN` | `true` | Offers in pesos at Banxico's rate; `false` keeps prices, offers and the minimum in USD |
| `BANXICO_TOKEN` | — | Free token from [Banxico SIE](https://www.banxico.org.mx/SieAPIRest/service/v1/token); required when converting to pesos |
| `POKEMONTCG_API_KEY` | — | Optional [pokemontcg.io](https://dev.pokemontcg.io) key for higher rate limits on the backup price source |

Settings are read once at startup. Restart the server after editing `.env`.

The condition factors and the minimum buy price in `config/reglas.yaml` are placeholders marked `TODO`. Set them with the shop.

### 3. Build the catalog and index

```bash
python scripts/fetch_catalog.py --since 1999-01-01     # ~19.7k cards, ~1.5 GB; safe to interrupt and re-run
python scripts/build_index.py --model dinov2 --lang en  # ~35 min on a laptop CPU
```

### 4. Run the server

```bash
uvicorn scanner.api:app --host 0.0.0.0 --port 8000
```

Phones on the shop's Wi-Fi reach it at `http://<shop-pc-ip>:8000`. Interactive API docs are at `/docs`.

| Endpoint | Purpose |
|---|---|
| `POST /identify` | Photo in; per card: top 3 matches, confidence, language flag, `needs_review`, crop URL |
| `POST /corrections` | Store the card the employee picked when the match was wrong |
| `POST /sessions` | Start a buy session (fixes the exchange rate for that customer) |
| `POST /sessions/{id}/cards` | Add a card: looks up its price and calculates the offer |
| `PATCH /sessions/{id}/cards/{card_id}` | Change condition, variant, manual price (USD) or accepted |
| `GET /sessions/{id}` | Cards with offers, plus cash and credit totals |
| `GET /settings` | Active currency, languages, conditions (read-only) |

### 5. Test

```bash
python -m pytest -q                              # unit and API tests; no network or models needed
python scripts/eval_phase1.py --threads 4        # identification QA gate; needs data/ built
```

## Data sources

| What | Source |
|---|---|
| Catalog and card images | [TCGdex](https://tcgdex.dev) (open data) |
| Market price (USD) | TCGplayer, via [TCGdex](https://tcgdex.dev) (main) and [pokemontcg.io](https://pokemontcg.io) (backup) |
| Exchange rate | [Banxico SIE](https://www.banxico.org.mx/SieAPIRest/), series SF43718 (FIX) |
| Recent sales | eBay sold-items search, opened by the employee (no scraping) |

## Known limits

- **No catalog image:** 1,592 English cards have no image on TCGdex (Shiny Vault, Shining Legends, Dragon Majesty, the Galleries). Photos of them come back marked for review.
- **Newest sets have no price:** the newest sets have no price for the first weeks (30th Celebration as of Oct 2026). Use the eBay link and a manual price.
- **Timing:** not yet measured on the shop PC.

See `docs/MVP.md` for the product and `docs/sequence-builder.md` for the phase plan. Contributors and coding agents: read `AGENTS.md` first.
