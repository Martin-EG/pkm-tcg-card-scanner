# Phase 1 — Identification service: results

Oct 14, 2026 · DINOv2 + OCR, full English catalog

## Verdict

Every [AUTO] gate item passes. With OCR, top-1 on the Phase 0 photos goes from 97.6% to **100%** (41/41). A 9-card page takes at most **7.4 s** on 4 CPU threads. Same-art reprints are told apart in **10/10** synthetic cases and **13/13** real photos.

Two things are still open:
- **Shop PC:** nothing has been timed on it yet. This Mac is fast, so the 7.4 s worst case leaves less margin than it looks.
- **Real 9-card page:** there's no photo of a full 9-card page yet. The 9-card timing comes from synthetic pages built from catalog images.

## QA gate

| item | result | evidence |
|---|---|---|
| [AUTO] Top-1 on the Phase 0 photos ≥ Phase 0 | **PASS** | 100% (41/41) vs 97.6%; top-3 100%. Same 3 catalog gaps left out as in Phase 0 |
| [AUTO] 9-card binder page < 10 s on CPU | **PASS** (this Mac) · **NEEDS MANUAL CHECK** (shop PC, real 9-card photo) | synthetic 9-card pages: 7.35 / 7.10 / 5.90 s, 9/9 correct each. Real pages: 6 cards 4.53 s, 4 cards 1.99 s |
| [AUTO] Same-art reprints told apart in ≥ 9 of 10 | **PASS** | 10/10 synthetic (5 same-art pairs, both directions, similarity 0.98–1.00); 13/13 real photos whose card has a same-name reprint in the top 3 |
| [AUTO] No card / blurry → clear error, never a made-up card | **PASS** | empty binder page → `no_card`; motion-blurred page → `blurry`. Only 1 real photo of each so far |
| [AUTO] With ENABLE_SPANISH / ENABLE_JAPANESE false, no Spanish or Japanese results | **PASS** | every candidate in every run is English. Spanish and Japanese cards are flagged instead (see below) |

Source: `python scripts/eval_phase1.py --threads 4`. Output is in `reports/phase1_eval.txt`, with per-photo detail in `reports/phase1_eval.json`. Machine: Apple M5, torch limited to 4 threads.

### [MANUAL] for the owner

1. **Time it on the shop PC.** Run `python scripts/eval_phase1.py --threads 4` there. The slowest page has to stay under 10 s.
2. **Take one real photo of a full 9-card binder page** and save it in `photos/binder/`. The pages so far have 6 and 4 cards, so the 9-card time is only measured on synthetic pages.
3. **Check my reading of the binder cards** in the table below, especially Mienfoo.
4. **Take more no-card and blurry photos** and save them in `photos/errors/`. The blur threshold (`quality.min_sharpness: 180`) is set from a single blurry photo (sharpness 118) against the least sharp good photo (261).

## What was built

- **`scanner/crop.py`: 1 to 9 cards per photo.**
  - Card outlines come from an edge map plus bright regions. The bright regions are what work in binders, where the card edge and the pocket edge blur together.
  - Junk is filtered out by corner angles, edge support and similar card sizes. A whole binder page, which has the same 63:88 shape as a card, is dropped when it contains other cards.
  - Single-card photos keep the Phase 0 GrabCut path. All 49 single-card photos still give exactly 1 card.
  - Blurry photos raise `PhotoError("blurry")` and photos with no card raise `PhotoError("no_card")`, each with a message in Spanish.
- **Full English catalog.** 19,663 cards from 150 sets (copied from the earlier project and checked against TCGdex: 0 new cards). The DINOv2 index is `data/index/dinov2_en.faiss`, 242 MB, built in 34 min.
- **`scanner/ocr.py`: PaddleOCR (mobile models, CPU).**
  - The English recognizer reads the left half of the bottom strip, and the right half when no number is found there (older cards print it on the right). It reads the set code, language tag and number/total.
  - The parser copes with typical misreads: `PREEN`, `SYIEJ203/198`, `JCRIEm`, `O10`, `CRLENAPOPE`. A set code must be read in capitals, so the word "Mega" doesn't count as the code MEG.
  - The text adds a bonus to matching candidates: +0.10 for the number, +0.05 for the set size, +0.08 for the code, +0.06 for the language.
  - Cards found by text alone are added when the image search missed them.
- **Language flag.** Spanish and Japanese indexes were left out for now, at the owner's request.
  - Every card is read. The bottom-strip tag gives `EN`, or `LA` for Latin American Spanish prints, which OCR often reads as `IA`. The name bar is read with the multilingual model: Japanese kana, BÁSICO / FASE, "Zorua de N".
  - A Spanish or Japanese card still gets its English matches, since the artwork is shared, plus `warning`: "Parece una carta en español… confirma la carta y el precio a mano" and `needs_review`.
- **`needs_review`.** A card is marked when its final score (similarity plus OCR bonus) is below 0.75, or when its language is flagged. In the binder photos this caught every wrong match. In the Phase 0 photos it marked 2 of 41, both correct but not confirmed by OCR.
- **API (`scanner/api.py`, FastAPI).**
  - `POST /identify` takes a photo and returns, per card: the top 3 (id, name, set, number, language, confidence, official image URL), `confident`, `needs_review`, `detected_language`, `warning` and the crop URL.
  - `POST /corrections` stores the card the employee picks.
  - `GET /images/...` and `GET /scans/...` serve files, with path traversal blocked.
  - Photos and crops go in `data/scans/<id>/`. Results and corrections go in SQLite (`data/scanner.db`).
  - Errors return HTTP 422 with `{"error": "blurry" | "no_card" | "bad_image", "message": ...}`.
- **Settings and rules.**
  - `scanner/settings.py` is a typed `.env` loader (`ENABLE_SPANISH`, `ENABLE_JAPANESE`, `CONVERT_TO_MXN`), with `.env.example`.
  - All thresholds moved to `config/reglas.yaml`, including Phase 0's artwork box.
  - Turning on a language that has no index logs a warning instead of crashing.
- **`scripts/fetch_catalog.py`.** Now uses the TCGdex REST API directly with `--lang`. The Python SDK fails on Spanish and Japanese sets and doesn't expose the printed set code. The set cache now stores each set's code and printed size, which OCR needs: 190 of 220 English sets have a code.
- **Tests.** 82 pass (`python -m pytest -q`).

## Binder photos, card by card

| photo | card read | match | score | marks | my check from the crop |
|---|---|---|---|---|---|
| IMG_3767 | Zekrom (Japanese print) | xy6-64 Zekrom | 0.69 | ja, review | Japanese card; flagged as intended |
| IMG_3767 | Zorua de N (Spanish print) | swsh11-183 Galarian Perrserker V | 0.67 | es, review | wrong match, but flagged and marked |
| IMG_3767 | Ethan's Typhlosion | sv10-190 | 0.80 visual, OCR-confirmed | — | right |
| IMG_3767 | Armarouge | sv01-203 | OCR `SVIEN 203/198` | — | right |
| IMG_3767 | Emboar | sv10.5w-098 | OCR `WHTEN 098/086` | — | right |
| IMG_3767 | Iono's Bellibolt ex | sv09-172 | 0.81 | — | right |
| IMG_3770 | Mankey | base2-55 (Jungle) | 0.68 | review | looks right; nothing printed for OCR to confirm |
| IMG_3770 | Machop | ex12-57 | OCR `57/92` | — | right |
| IMG_3770 | Machamp | det1-13 | OCR `13/18` | — | right |
| IMG_3770 | Mienfoo | sv10.5w-052 | 0.60 | review | **unsure; please confirm** |

`IMG_3767`'s top row is cut off by the frame, so 6 of its 8 cards are detected. That's intended: a partial card can't be matched reliably.

## Known limits

- **Catalog gaps:** 1,592 English cards have no image on TCGdex. Among them are popular subsets: Shiny Vault (122), Shining Legends (78), Dragon Majesty (78), Galarian Gallery (70) and the Trainer Galleries. Photos of those cards come back marked `needs_review`, never confident.
- **The language flag is best effort.** It needs either the `LA` tag or a Spanish word or Japanese name to be read. Japanese cards are flagged only through the name bar.
- **A crop that isn't a card** in a multi-card photo, like a wallet on the table, still gets candidates, marked `needs_review`. Only a single crop with no match turns into the `no_card` error.
- **macOS dev machines** need `scripts/fix_macos_openmp.sh` once after installing (torch and faiss each ship their own OpenMP library).
- **iCloud:** `data/` is a symlink to `data.nosync/` so iCloud doesn't sync 1.6 GB of images. Not needed on the shop PC.

## Next

Phase 2: prices (pokemontcg.io), exchange rate (Banxico SF43718), and the cash and store-credit offer.
