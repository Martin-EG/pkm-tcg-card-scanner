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

## Using the app

The phone app is in Mexican Spanish, with large buttons for one-handed use and three tabs at the bottom.

- **Escanear:** pick **1 carta** or **Página de 9**, frame the cards inside the guide, and tap **Tomar foto**. The first photo starts a new buy session.
- **Cartas:** every card in the purchase, newest first, with the photo next to the official image.
  - Confident matches are added automatically. Uncertain ones (low confidence, Spanish or Japanese prints, cards with no catalog image) ask **"¿Cuál es?"** with 3 options, or **Ninguna, descartar**.
  - Per card: condition (**NM** by default), variant, **Buscar vendidos en eBay**, a manual price in US$, and **El cliente la vende / se la queda**.
  - **Quitar de la compra** takes a card out of the purchase and its totals. **Deshacer** brings it back for 6 seconds afterwards. The card is kept in the database, marked as removed, for later review.
- **Resumen:** the screen to show the customer. It has the currency, the Banxico rate with its date, cash and credit totals, and each card's offer and price source. **Exportar CSV** saves the purchase for inventory; **Nueva compra** starts the next customer.

**No connection to the shop PC:** the app says so and keeps the purchase on the phone. Changes made meanwhile, including removed cards, are sent when the PC is reachable again. New photos need the PC, so the shutter waits for it.

## Status

| Phase | What | State |
|---|---|---|
| 0 | Identification proof of concept (image only) | done: [results](docs/phase0-results.md) |
| 1 | Identification service: multi-card crop, OCR, `POST /identify` | done: [results](docs/phase1-results.md) |
| 2 | Prices, exchange rate, offers, buy sessions | done: [results](docs/phase2-results.md) |
| 3 | Counter app (React + Vite PWA, Mexican Spanish UI) | built; phone checks pending: [results](docs/phase3-results.md) |
| 4 | Test at a shop | planned |

Spanish and Japanese catalogs are deferred for now. Cards printed in those languages are flagged for the employee to check.

## Project structure

```
app/                        Phone app (React + Vite PWA, Mexican Spanish UI), served by the server
server/                     Python server (FastAPI)
  main.py                   Entry point: uvicorn server.main:app
  paths.py                  Where data, config, certificates and the built app live
  config/
    settings.py             .env loader (languages, USD→MXN, API tokens)
    rules.py                reglas.yaml loader and validated pricing rules
  api/
    app.py                  App factory: wires services, error handlers, mounts the phone app
    deps.py, schemas.py     Shared services for routes; request bodies
    routes/                 identify.py · sessions.py · settings.py · files.py
  recognition/              Photo → card
    crop.py                 Card detection and perspective correction (1–9 cards, blur and no-card errors)
    embedders.py, index.py  DINOv2 / CLIP embeddings and the FAISS index per language
    ocr.py                  PaddleOCR: set code, number, language
    catalog.py              Catalog rows joined with set info (printed code, set size)
    identify.py             Crop → embed → search → OCR re-rank → review flags
  pricing/                  Card → price → offer
    tcgdex.py               Main price source (TCGplayer market price via TCGdex)
    pokemontcg.py           Backup price source (pokemontcg.io) · setmap.py: its set mapping
    prices.py               Provider order and daily price cache
    quote.py                Shared price model and "unavailable" error
    fx.py, ebay.py          Banxico exchange rate · eBay sold-items link
    offer.py                Offer formula
  sessions/service.py       Buy sessions: cards, prices, offers, totals
  storage/db.py             SQLite (data/scanner.db): scans, corrections, price cache, FX rates, sessions
config/reglas.yaml          Business rules and every tunable threshold (shares, factors, minimum, crop, OCR)
.env.example                Server settings: languages, USD→MXN conversion, API keys
scripts/
  fetch_catalog.py          Download the TCGdex catalog and card images (resumable)
  fill_image_gaps.py        Add cards TCGdex has no image for, with pokemontcg.io images (resumable)
  build_index.py            Embed the catalog into a FAISS index (--append: only new cards)
  eval.py, eval_phase1.py   Phase 0 and Phase 1 QA evaluations (evaluation.py: shared helpers)
  make_cert.py              Local HTTPS certificate for the shop network (see below)
  fix_macos_openmp.sh       macOS only: make faiss and torch share one OpenMP runtime
tests/                      pytest suite, grouped like server/ (recognition, pricing, api, config, scripts)
photos/                     Labeled test photos (<tcgdex id>.heic), binder pages, Spanish cards
docs/                       MVP, phase plan, per-phase results (Phase 0–2 docs use the old scanner/ paths)
reports/                    Evaluation output committed with each phase
data/                       Catalog, images, indexes, scanner.db, scans, certificates (git-ignored, ~2 GB)
                            (scans/_older/: scan folders moved aside when a new database reuses their number)
```

## Getting started

Requires Python 3.11+, Node.js 20+ (only to build the phone app), and about 3 GB of disk space. The shop PC needs no GPU.

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
python scripts/fill_image_gaps.py                       # +~785 cards TCGdex has no image for, from pokemontcg.io
python scripts/build_index.py --model dinov2 --lang en  # ~35 min on a laptop CPU
```

After adding cards later (a new set, or re-running `fill_image_gaps.py`), `python scripts/build_index.py --model dinov2 --append` embeds only the new ones in about a minute.

### 4. Build the phone app

```bash
cd app && npm install && npm run build && cd ..
```

The server serves the built app (`app/dist`) at its root address, so phones need nothing else installed.

### 5. HTTPS on the shop network

Phones allow the live camera and installing the app only on HTTPS pages. Create a certificate for the shop PC once:

```bash
python scripts/make_cert.py
```

It creates a small certificate authority for the shop (`data/certs/ca.pem`, made once) and a certificate for this PC's addresses. Re-run it if the PC's IP changes; reserving the IP in the router avoids that.

### 6. Run the server

```bash
uvicorn server.main:app --host 0.0.0.0 --port 8443 --ssl-certfile data/certs/server.pem --ssl-keyfile data/certs/server.key
```

See [API](#api) for the endpoints.

### 7. Set up each phone (once)

1. Connect the phone to the shop's Wi-Fi.
2. Open `https://<shop-pc-ip>:8443/certificado` and download the certificate. The browser warns that the site isn't trusted yet; continue to the site, since that's the point of this step.
3. Install the certificate:
   - **iPhone:** Settings → General → VPN & Device Management → install the downloaded profile. Then go to Settings → General → About → Certificate Trust Settings and turn on full trust for "TCG Buylist Scanner – tienda local".
   - **Android:** Settings → Security → Encryption & credentials → Install a certificate → CA certificate, and pick the downloaded file. The menu names vary by phone.
4. Open `https://<shop-pc-ip>:8443`. There should be no warning now.
5. Add it to the home screen:
   - **iPhone:** iOS never offers to install a web app, so the app shows a notice with the steps. In **Safari** (other iPhone browsers may not have the option), tap Share → **Agregar a pantalla de inicio** → Agregar. The notice goes away once the app runs from the home screen, or after **Entendido**.
   - **Android:** browser menu → Install app.

Without these steps the app still works over `http://<shop-pc-ip>:8000` (run uvicorn without the `--ssl-*` options), but it uses the phone's own camera app instead of the live camera with the guide frame, and it can't be installed.

After pulling an update, rebuild the app (step 4) and restart the server. The phones pick up the new version the next time they open the app, sometimes on the second load.

### 8. Test

```bash
python -m pytest -q                              # server: unit and API tests; no network or models needed
cd app && npm test                               # phone app: offline queue, summary, picker, card removal, iPhone notice, CSV
python scripts/eval_phase1.py --threads 4        # identification QA gate; needs data/ built
```

## API

The phone app talks to these endpoints; interactive docs are at `/docs` on the running server.

| Endpoint | Purpose |
|---|---|
| `POST /identify` | Photo in; per card: top 3 matches, confidence (0–1), language flag, `needs_review`, crop URL |
| `POST /corrections` | Store the card the employee picked when the match was wrong |
| `POST /sessions` | Start a buy session (fixes the exchange rate for that customer) |
| `GET /sessions/{id}` | Cards with offers, plus cash and credit totals (removed cards left out) |
| `POST /sessions/{id}/cards` | Add a card: looks up its price and calculates the offer |
| `PATCH /sessions/{id}/cards/{card_id}` | Change condition, variant, manual price (USD) or accepted |
| `DELETE /sessions/{id}/cards/{card_id}` | Remove a card from the purchase and its totals (kept in the database, marked removed) |
| `POST /sessions/{id}/cards/{card_id}/restore` | Undo a removal |
| `GET /settings` | Active currency, languages, conditions (read-only) |
| `GET /certificado` | The shop's certificate authority, for phones to install |

## Data sources

| What | Source |
|---|---|
| Catalog and card images | [TCGdex](https://tcgdex.dev) (open data); [pokemontcg.io](https://pokemontcg.io) images for cards TCGdex has none for |
| Market price (USD) | TCGplayer, via [TCGdex](https://tcgdex.dev) (main) and [pokemontcg.io](https://pokemontcg.io) (backup) |
| Exchange rate | [Banxico SIE](https://www.banxico.org.mx/SieAPIRest/), series SF43718 (FIX) |
| Recent sales | eBay sold-items search, opened by the employee (no scraping) |

## Known limits

- **No catalog image:** after `fill_image_gaps.py`, about 800 English cards still have no image from either source, mostly MEP promos, My First Battle, trainer kits and the MEE energies. Photos of them come back marked for review.
- **Newest sets have no price:** the newest sets have no price for the first weeks (30th Celebration as of Oct 2026). Use the eBay link and a manual price.
- **Timing:** not yet measured on the shop PC.
- **iPhone installation is manual:** iOS has no install prompt (the app explains the steps), and the shop certificate has to be trusted by hand on each phone.

## Upgrading

- **`data/server.storage.db` exists:** versions between the server reorganization and the database-path fix wrote to `data/server.storage.db` by mistake. Stop the server, keep a copy of the old file (`mv data/scanner.db data/scanner.db.before-fix`), then `mv data/server.storage.db data/scanner.db`, and start the server again.

See `docs/MVP.md` for the product and `docs/sequence-builder.md` for the phase plan. Contributors and coding agents: read `AGENTS.md` first.

## License

Apache License 2.0, see [LICENSE](LICENSE). The models it runs, DINOv2 and PaddleOCR, are Apache 2.0 too.
