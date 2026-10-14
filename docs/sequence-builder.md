# Build Sequence — Pokémon Card Scanner

Oct 12, 2026 · @Martin

Five phases, 2 to 3 weeks in total after the print shop project ships. Phase 0 decides whether the project continues: if English identification doesn't reach 85% on real photos, that gets fixed before building anything else.

## How to use the prompts

Save the context as `AGENTS.md` (or `CLAUDE.md`) at the repository root and paste each phase's prompt into your coding agent. Don't move to the next phase until its checklist passes.

**Project context (once)**

```text
# TCG Buylist Scanner

Project: Pokémon card scanner for small TCG shops in Mexicali, Mexico. The employee photographs cards with a phone; the system identifies them, looks up their price, and calculates the buy offer in cash and in store credit.

Constraints:
- The server runs on a shop PC, probably with no GPU. The phone only takes photos and shows results over the local Wi-Fi network.
- Identification is 100% local with open models: image embeddings (CLIP/SigLIP/DINOv2) + FAISS index + PaddleOCR. Customer photos never leave the shop.
- Catalog and reference images: TCGdex. English is always on; Spanish and Japanese are optional languages toggled with environment variables.
- Prices: pokemontcg.io (TCGplayer market price, USD). eBay sold items: no API; open the search and enter manually. Exchange rate: Banxico SIE series SF43718, used only when CONVERT_TO_MXN is true.
- All business rules live in config/reglas.yaml. No hardcoded values.
- Stack: Python 3.11+, FastAPI, OpenCV, FAISS, PaddleOCR, SQLite; React + Vite as a PWA.
- Code and comments in English; UI in Mexican Spanish.
- pytest tests.

Offer rules:
- offer = price_usd * (exchange_rate if CONVERT_TO_MXN else 1) * condition_factor * (0.85 cash | 0.90 credit)
- Conditions: NM, LP, MP, HP, DMG; factors to be set with the shop (configurable).
- Configurable minimum buy price per card.
- Settings come from environment variables (.env), read once at startup with a typed loader; changing one means editing .env and restarting the server. No settings screen yet. Defaults: ENABLE_SPANISH=false, ENABLE_JAPANESE=false, CONVERT_TO_MXN=true. When CONVERT_TO_MXN is false, prices, offers, and the minimum are in USD.
- Every offer stores the price, source, date, and exchange rate used. A manually entered price is marked as manual.

How to work:
- Propose a short plan before writing code and wait for my OK.
- Small steps, tests at the end of each step.
- If something isn't defined here, ask.
- Every phase prompt ends with a QA gate. Check every item, report PASS / FAIL / NEEDS MANUAL CHECK with evidence, and never call a phase done while any item fails. [AUTO] items you verify yourself; [MANUAL] items are for me, so list them for me to confirm.
```

## Phase 0 — data and identification proof of concept (2–3 days)

Before building the app, prove that a phone photo finds the right card.

**Must-haves**

- [ ] Download the English catalog and card images from TCGdex (start with sets from the last 3 years, which is what gets bought most)
- [ ] Compute embeddings with 2 open models (for example CLIP and DINOv2) and store them in a FAISS index
- [ ] Take 50 real phone photos at the counter, in normal light, some with sleeves or glare
- [ ] Measure how often the right card ranks 1st and in the top 3
- [ ] Ask the shop for 10–20 Spanish and Japanese cards for the same test

**Quality checklist**

- [ ] English: right card 1st in 85% or more, and in the top 3 in 95% or more
- [ ] Each search takes under 2 seconds on a no-GPU PC
- [ ] It's written down which model won and why, and what kind of photo it fails on

**Agent prompt**

```text
Read AGENTS.md. Phase 0: identification proof of concept. Scripts only, no API or app.

1. scripts/fetch_catalog.py: download from TCGdex (Python SDK) the English catalog for sets from the last 3 years with high-resolution images. Save data/catalog_en.jsonl (id, name, set, number, language, image path). Respect API limits and support resuming.
2. scripts/build_index.py --model {clip,dinov2}: compute embeddings for all images and save one FAISS index per model.
3. scripts/eval.py: take a folder of real phone photos named with the correct card id (for example sv06-123.jpg), crop the card with a simple contour detector, search each index, and report: top-1 accuracy, top-3 accuracy, average search time on CPU, and the list of failures.
4. Print a table comparing both models.

Don't add OCR yet; I want to see how far the image alone gets.

QA gate (Phase 0 is done only when every item passes):
- [AUTO] English: correct card ranked 1st in 85% or more of the real photos, and in the top 3 in 95% or more
- [AUTO] Each search takes under 2 seconds on CPU
- [AUTO] docs/phase0-results.md records which model won, why, and the kinds of photos it fails on

Finish with a table: item | PASS / FAIL / NEEDS MANUAL CHECK | evidence (command output, test name, or measurement). If an [AUTO] item fails, try to fix it and re-run; if accuracy still misses the target, stop and tell me instead of moving on.
```

## Phase 1 — crop, identification, and OCR (3–4 days)

From proof of concept to a service: it takes a photo with one or more cards and returns each card identified with its confidence.

**Must-haves**

- [ ] OpenCV crop: detect card outlines, correct perspective, support 1 to 9 cards per photo
- [ ] Expand the index to the full English catalog; build separate Spanish and Japanese indexes that load only when enabled via environment variables
- [ ] PaddleOCR for collector number and set code; use it to break ties among the top 3
- [ ] Detect language from the text read
- [ ] `POST /identify` endpoint that returns, per card: top 3, confidence, language, cropped image
- [ ] Store every employee correction (photo + correct card) for later improvement

**Quality checklist**

- [ ] On the 50 Phase 0 photos, top-1 accuracy goes up or holds
- [ ] A 9-card binder page is processed in under 10 seconds
- [ ] Reprints with the same artwork are told apart by collector number in at least 9 of 10 test cases
- [ ] A photo with no cards or a blurry one returns a clear error, not a made-up card

**Agent prompt**

```text
Read AGENTS.md. Phase 1: identification service using the model that won Phase 0.

1. scanner/crop.py: detect 1 to 9 cards in a photo (63x88 mm aspect ratio), correct perspective, and return each crop. Handle photos with no cards or blurry photos with a clear error.
2. Expand the catalog and index to all English cards. Build separate Spanish and Japanese indexes (where TCGdex has an image) and search only the languages enabled by ENABLE_SPANISH and ENABLE_JAPANESE.
3. scanner/ocr.py: with PaddleOCR, read the bottom strip of the card (collector number and set code) and detect the language from the text. Use it to reorder the visual top 3 when the number matches.
4. FastAPI: POST /identify (photo) -> per card: top 3 with id, name, set, number, language, confidence, and official image; plus the crop. Store each photo and result in SQLite.
5. POST /corrections: store the correct card chosen by the employee.
6. Tests: fixture photos with 1 and 9 cards, reprints with the same artwork, a photo with no cards. Report the time for a 9-card page on CPU.

QA gate (Phase 1 is done only when every item passes):
- [AUTO] Top-1 accuracy on the 50 Phase 0 photos is equal to or higher than Phase 0
- [AUTO] A 9-card binder page is processed in under 10 seconds on CPU
- [AUTO] Reprints with the same artwork are told apart by collector number in at least 9 of 10 test cases
- [AUTO] A photo with no cards or a blurry photo returns a clear error, never a made-up card
- [AUTO] With ENABLE_SPANISH and ENABLE_JAPANESE false, no Spanish or Japanese results are returned

Finish with a table: item | PASS / FAIL / NEEDS MANUAL CHECK | evidence. If an [AUTO] item fails, fix it and re-run before reporting.
```

## Phase 2 — prices, exchange rate, and offer (2–3 days)

With the card identified, the system calculates the offer in pesos using the shop's rules; no percentage or factor is written in code.

**Must-haves**

- [ ] pokemontcg.io client: TCGplayer market price per card and variant (normal, holo, reverse holo)
- [ ] Daily price cache, so it works offline with what's already been looked up
- [ ] Banxico SIE client (series SF43718) with a free token; use the latest published value and show its date; skipped entirely when CONVERT\_TO\_MXN is false
- [ ] Button that opens the eBay sold-items search for the card, and a field to enter the price manually (Japanese, Spanish, cards without a price)
- [ ] `reglas.yaml`: 85% cash, 90% credit, condition factors, minimum buy price (language and currency toggles live in .env)
- [ ] Offer calculation per card and total per session

**Quality checklist**

- [ ] The MVP doc example (US$10, $18.50, NM) gives $157.25 cash and $166.50 credit with conversion on, and US$8.50 and US$9.00 with it off
- [ ] Every offer stores the price, source, date, and exchange rate used
- [ ] A manually entered price is marked as manual in the summary
- [ ] Automated tests: each condition, a card below the minimum, a card without a price

**Agent prompt**

```text
Read AGENTS.md. Phase 2: prices, exchange rate, and offer.

1. .env.example with ENABLE_SPANISH=false, ENABLE_JAPANESE=false, CONVERT_TO_MXN=true, plus a settings loader (pydantic-settings). config/reglas.yaml: cash_pct 0.85, credit_pct 0.90, condition_factors (NM, LP, MP, HP, DMG; provisional values marked TODO), min_offer_mxn. Validated loader.
2. pricing/tcgplayer.py: pokemontcg.io client (API key in an environment variable) that returns the TCGplayer market price per variant (normal, holofoil, reverseHolofoil, 1stEdition). Map the TCGdex id to the pokemontcg.io id by set and number; if there's no mapping or price, return None.
3. Daily cache in SQLite per card and variant, so it works offline with what's already been looked up.
4. pricing/fx.py: Banxico SIE client, series SF43718 (token in an environment variable). Use the latest published value and store its date. Only called when CONVERT_TO_MXN is true.
5. pricing/ebay.py: only build the eBay sold-items search URL for the card (name + set + number + language). No scraping.
6. offer.py: calculate the cash and credit offer per card and the total per session; accept a manual price and mark it as such; mark cards below the minimum as "not buying".
7. Endpoints: POST /sessions, POST /sessions/{id}/cards, PATCH /sessions/{id}/cards/{card_id} (condition, variant, manual price, accepted), GET /sessions/{id}, GET /settings (read-only, so the app knows the active currency and languages).
8. Tests: US$10 with FX 18.50 and factor 1.0 = 157.25 cash and 166.50 credit; same card with conversion off = 8.50 and 9.00 USD; Spanish and Japanese results never appear when those toggles are off; each condition; a card below the minimum; a card without a price.

QA gate (Phase 2 is done only when every item passes):
- [AUTO] US$10, FX 18.50, NM factor 1.0 gives 157.25 cash and 166.50 credit with CONVERT_TO_MXN true, and 8.50 and 9.00 USD with it false
- [AUTO] Every offer stores the price, source, date, and exchange rate used (no rate stored when conversion is off)
- [AUTO] A manually entered price is flagged as manual
- [AUTO] Tests pass for each condition, a card below the minimum, and a card without a price
- [AUTO] No percentage, factor, or minimum is hardcoded outside config/ and .env

Finish with a table: item | PASS / FAIL / NEEDS MANUAL CHECK | evidence. If an [AUTO] item fails, fix it and re-run before reporting.
```

## Phase 3 — counter app (3–4 days)

The phone web app ties everything together: photo, confirmation, condition, and customer summary.

**Must-haves**

- [ ] React PWA opened from a phone connected to the shop network
- [ ] Camera screen with a guide for framing one card or a binder page
- [ ] Session card list: cropped photo next to the official image, name, set, language
- [ ] Tap to choose among the 3 options when confidence is low
- [ ] Condition selector (NM by default) and variant selector; show the active currency (read from GET /settings)
- [ ] Customer summary: offer per card, cash and credit totals, exchange rate with date when conversion is on
- [ ] Mark accepted cards and export to CSV

**Quality checklist**

- [ ] A card is added in under 10 seconds from photo to seeing its offer
- [ ] Usable one-handed, with comfortably sized buttons on a phone screen
- [ ] The summary is understandable without explanation (test with someone outside the shop)
- [ ] If the connection to the server drops, the app says so and doesn't lose the session

**Agent prompt**

```text
Read AGENTS.md. Phase 3: counter app as a PWA with React + Vite.

1. Installable on the phone, connected to the server over the local network (the server address is configured once).
2. Camera screen with a guide frame for one card or a 9-card page; uploads the photo to /identify.
3. Session list: crop next to the official image, name, set, number, language. If confidence is low, show the 3 options to pick with one tap and send the correction.
4. Per card: condition selector (NM by default), variant, a "Search eBay sold" button that opens the URL, and a manual price field.
5. Customer summary: offer per card, cash and credit totals, exchange rate with its date, and each price's source. Designed to be readable when the screen is shown to the customer.
6. Mark accepted cards and export the session to CSV (columns: id, name, set, number, language, variant, condition, price_usd, source, exchange_rate, cash_offer, credit_offer, accepted).
7. If the connection drops, show a notice and keep the session on the phone until it reconnects.
8. Read GET /settings at startup. No settings screen yet; settings change through .env on the server. The summary always shows which currency is in use, and hides the exchange rate when conversion is off.

Large buttons, one-handed use, all UI text in Spanish.

QA gate (Phase 3 is done only when every item passes):
- [MANUAL] A card is added in under 10 seconds from photo to seeing its offer (measure on a real phone)
- [MANUAL] The app is usable one-handed with comfortably sized buttons
- [MANUAL] Someone outside the shop understands the customer summary without explanation
- [AUTO] When the server connection drops, the app shows a notice and keeps the session (test)
- [AUTO] The summary shows the active currency and hides the exchange rate when conversion is off

Finish with a table: item | PASS / FAIL / NEEDS MANUAL CHECK | evidence. If an [AUTO] item fails, fix it and re-run before reporting.
```

## Phase 4 — shop test (3–5 days of use)

The scanner is used on real buys in one of the shops you know, with manual valuation as backup.

**Must-haves**

- [ ] Before installing, resolve the MVP doc's open questions with the shop (factors, minimum, exchange rate, CSV)
- [ ] Install the server on the shop computer and access on the counter phone
- [ ] Value at least one 100+ card collection twice: by hand and with the scanner, timing both
- [ ] Log identification accuracy per language and offer differences
- [ ] At the end, ask the owner: what it saved them, what's missing, and how much they'd pay per month
- [ ] Repeat with the second shop if the first goes well

**Quality checklist**

- [ ] No real buy was paid wrong because of the scanner
- [ ] The MVP doc's metrics are measured with real numbers
- [ ] The shop's next request is written down (probably automatic condition grading or inventory)

**Agent prompt**

```text
Read AGENTS.md. Phase 4: installation and measurement at the shop.

1. scripts/install_store.md + an install script for the shop PC (Windows or Linux): dependencies, copying the precomputed index, environment variables, auto-starting the server.
2. Log per session: number of cards, start and end time, cards identified on the first try per language, corrections, manual prices, and total offered.
3. scripts/report.py: Markdown summary with minutes per 100 cards, top-1 accuracy per language, % of manual prices, and the difference vs. a manual valuation I enter in samples/manual_valuation.csv.
4. A notes field per session for the owner's comments; the report includes them.

Don't change offer rules in this phase; only fix bugs that show up.

QA gate (Phase 4 is done only when every item passes):
- [AUTO] The install script runs cleanly on a fresh machine and the server starts automatically
- [MANUAL] No real buy was paid wrong because of the scanner
- [AUTO] scripts/report.py produces every metric from the MVP doc with real numbers
- [MANUAL] The shop's next request is written down in the session notes

Finish with a table: item | PASS / FAIL / NEEDS MANUAL CHECK | evidence. If an [AUTO] item fails, fix it and re-run before reporting.
```

## What to cut if you fall behind

Cut from the top down; English identification and offer calculation are never cut.

| If you're behind | Cut | What remains |
| --- | --- | --- |
| A little | Multiple cards per photo | One card per photo |
| Moderately | Automatic Japanese | Japanese is searched manually in the list; price always manual |
| Quite a bit | Installable PWA with its own camera | A simple web page that uses the browser camera to upload the photo |
| A lot | CSV export and per-card condition | One condition for the whole session; the summary is copied by hand |
