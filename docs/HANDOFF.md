# Handoff — Phase 0 (identification proof of concept)

Oct 14, 2026. Branch `claude/busy-darwin-kvhshk`. Read `AGENTS.md` first: it holds the project rules (plan before code, wait for OK, QA gate with PASS / FAIL / NEEDS MANUAL CHECK, code in English, UI in Mexican Spanish).

## The task (as the owner gave it)

Phase 0: scripts only, no API or app, **no OCR yet** ("see how far the image alone gets").

1. `scripts/fetch_catalog.py`: English TCGdex catalog with high-res images → `data/catalog_en.jsonl`. Respect API limits, support resuming.
2. `scripts/build_index.py --model {clip,dinov2}`: one FAISS index per model.
3. `scripts/eval.py`: photos named `<card id>.jpg`; crop the card, search each index; report top-1, top-3, average CPU search time, and failures.
4. A table comparing both models.

QA gate (Phase 0 is done only when every item passes):
- [AUTO] English: correct card 1st in ≥ 85% of real photos, top 3 in ≥ 95%
- [AUTO] Each search < 2 s on CPU
- [AUTO] `docs/phase0-results.md` records which model won, why, and what photos it fails on

Owner's rule: if an [AUTO] item fails, try to fix it and re-run. **If accuracy still misses the target, stop and tell the owner instead of moving on.**

## Decisions already made with the owner

- Catalog scope: **all of Scarlet & Violet and later** (`--since 2023-03-01`), including promos (SVP, MEP), energies and 30th Celebration. TCG Pocket (`tcgp`) excluded.
- Timing means end to end per photo (decode + crop + embed + search), judged by the **slowest** photo.
- Photos live in the repo under `photos/` (public for now, to be made private later).
- Simple contour crop didn't work on real photos. The crop now uses **GrabCut** (region segmentation, then contour → quad → perspective warp). This deviates from the "simple contour detector" wording; the owner was told and didn't object.

## Code map

| Path | What |
|---|---|
| `scripts/fetch_catalog.py` | TCGdex SDK; rate limit 5 req/s shared across 4 download threads; retries 429/5xx with backoff; resumable (skips ids already in the JSONL whose image exists; compacts broken lines); caches set dates in `data/cache/sets_en.json` |
| `scanner/crop.py` | GrabCut at 256 px (`SEGMENT_MAX_SIDE`), seeded RNG, falls back to the full photo if no card-shaped region |
| `scanner/embedders.py` | CLIP `ViT-B-32-quickgelu`/`openai` (open_clip) and `facebook/dinov2-base` (CLS + mean patch). Images squashed to 224×224. `embed_cards()` = whole card + **artwork box** (`ART_BOX`, `ART_WEIGHT = 0.5`), weighted and concatenated |
| `scanner/index.py` | `faiss.IndexFlatIP` over unit vectors + `<model>_ids.json` |
| `scanner/evaluation.py` | filename → id (`sv06-123_2.jpg` → `sv06-123`), top-k metrics |
| `scripts/build_index.py` | embeds the catalog → `data/index/<model>.faiss` |
| `scripts/eval.py` | crop + embed (upright and rotated 180°, best score per id) + search; prints per-model failures and the comparison table; `--save-crops`, `--no-flip`, `--models` |
| `tests/` | 25 pytest tests (crop on synthetic cards, filename parsing, metrics, fetch resume with a fake SDK, embed_cards weighting) |
| `docs/phase0-results.md` | results write-up — **stale: describes the 20-photo run; must be rewritten** |
| `reports/phase0_eval_en.txt`, `.json` | latest committed eval: 44 photos, **before** the artwork embedding |

## Set up locally

`data/` is git-ignored, so the catalog and indexes must be regenerated (~290 MB of images).

```bash
python -m venv .venv && . .venv/bin/activate
pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu   # CPU build, no CUDA download
pip install -r requirements.txt
python -m pytest -q                                   # expect 25 passed
python scripts/fetch_catalog.py --since 2023-03-01    # ~15-20 min; safe to interrupt and re-run
python scripts/build_index.py --model dinov2          # ~15 min on 4 cores
python scripts/build_index.py --model clip            # ~7 min
python scripts/eval.py --photos photos/en --save-crops
```

Expected catalog: 31 sets, **4,742 cards** with images (250 listed cards have no image on TCGdex).

## Where it stopped

The artwork-box embedding was committed, but the index rebuild with it **did not finish**: the cloud session ended mid-build. **Next step: rebuild both indexes and run the eval** (commands above). Old indexes built before `embed_cards` have the wrong dimension and won't work with the current code.

## Results so far

**44 English photos, before the artwork embedding** (committed in `reports/`):

| model | top-1 | top-3 | mean s | max s |
|---|---|---|---|---|
| CLIP | 84.1% | 86.4% | 0.71 | 1.25 |
| DINOv2 | 84.1% | 93.2% | 0.78 | 1.37 |

→ Both accuracy items **FAIL**; timing passes.

**Artwork-box experiment** (DINOv2, on the saved crops, art weight 0.3–0.7 all equal): **top-1 40/44 = 90.9%, top-3 41/44 = 93.2%**. It fixed Wimpod (reverse holo), Gengar (bad crop + stamp) and Froakie. Vaporeon also became correct, but only by luck (same art as another card). Not yet confirmed by the real pipeline run.

### DINOv2's misses, by kind

| photo | why | fixable by image? |
|---|---|---|
| `mee-010`, `mee-014` | 30th-anniversary basic energies; TCGdex's MEE set lists only 001–008, without images | No: catalog gap |
| `mep-078` (Toxel) | on TCGdex but no image | No: catalog gap |
| `sv03.5-004` Charmander | same artwork as `sv04.5-007` | No: needs OCR of set code and number (Phase 1) |
| `sv08.5-022` Vaporeon | same artwork as `sv03.5-134` | No: needs OCR |
| `me04-025` Wimpod | reverse holo foil changes the lower half | Yes: fixed by the artwork embedding |
| `sv04.5-057` Gengar | crop cut the top on white marble; Trick-or-Trade stamp | Yes: fixed by the artwork embedding |

**Top-3 ceiling is 41/44 = 93.2%** with the current photos, because of the 3 catalog gaps. So the top-3 gate item **cannot pass by image matching alone**. Per the owner's rule, after the re-run: if top-3 still misses, **stop and ask the owner**. The options to offer:
1. Find another image source for cards TCGdex lacks (e.g. pokemontcg.io images), or let the employee enter them by hand.
2. Count catalog gaps separately from model accuracy (in-catalog English: 41 photos).

## Photos

- `photos/en/`: 44 English photos, named `<tcgdex id>.heic`. Labels were read from the printed set code and number and checked against catalog names. **The owner hasn't confirmed them yet** ([MANUAL]).
- `photos/es/`: 2 Spanish (`sv09-163`, `svp-189`). Both matched their English print at rank 1.
- `photos/en-out-of-scope/`: 3 old cards (2004 EX Deoxys Sceptile, 2010 HGSS Entei promo, 2022 Silver Tempest Radiant Jirachi), unlabeled, excluded from the eval.
- Notes: `sv04.5-057` is the Trick-or-Trade pumpkin-stamped Gengar (TCGdex has no separate stamped card). Several `me04-*` cards are reverse holos. When the owner adds photos on `main` they arrive as `photos/en/IMG_*.HEIC`, often re-adding already-labeled ones; keep the labeled copies and drop the duplicates.

## After the re-run

1. Update `docs/phase0-results.md` with the 44-photo numbers, the artwork embedding, and the failure kinds above.
2. Commit `reports/` (git-ignored: use `git add -f reports/phase0_eval_en.txt reports/phase0_eval.json`).
3. Report the QA gate table to the owner. Open [MANUAL] items: confirm labels, time a search on the shop PC, 10–20 Spanish/Japanese cards from the shop (2 Spanish, 0 Japanese so far).

## Gotchas

- `HoughLinesP` returns shape `(N, 4)` in OpenCV 5, not `(N, 1, 4)` (only relevant if line detection comes back).
- Model weights come from Hugging Face; first use downloads ~350 MB (DINOv2) + ~350 MB (CLIP).
- Commits end with the attribution lines used in the git log on this branch.
