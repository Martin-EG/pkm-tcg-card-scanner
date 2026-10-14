# Phase 0 — Identification proof of concept: results

Oct 14, 2026 · image only, no OCR

## Verdict

**DINOv2 wins.** On the 41 real English counter photos whose card is in the index, it ranks the correct card 1st in 97.6% (40/41) and in the top 3 in 100% (41/41). The slowest photo took 0.78 s end to end with torch limited to 4 CPU threads. CLIP gets 95.1% / 97.6% on the same photos.

| model | photos scored | catalog gaps | top-1 | top-3 | mean s | max s | card found |
|---|---|---|---|---|---|---|---|
| CLIP ViT-B/32 (OpenAI) | 41 | 3 | 95.1% | 97.6% | 0.412 | 0.762 | 100% |
| **DINOv2 ViT-B/14** | 41 | 3 | **97.6%** | **100.0%** | 0.591 | 0.783 | 100% |

Source: `python scripts/eval.py --photos photos/en --threads 4`. The full output is in `reports/phase0_eval_en.txt` and per-photo detail is in `reports/phase0_eval.json`.

### How photos are scored

44 English photos were taken. 3 of them show cards that **have no image in the index** (catalog gaps, see below). No image model can match a card it has never seen, so, as agreed with the owner, these photos are **left out of top-1/top-3 and reported separately**. They still count toward timing and crop rate. In the app, a card with no catalog image will go to manual entry.

For comparison, with all 44 photos counted DINOv2 gets 90.9% top-1 (40/44) and 93.2% top-3 (41/44).

**Caveat on sample size:** 41 photos is a small sample. The 95% confidence interval for 40/41 is roughly 87–100%.

## Why DINOv2 won

- **More correct and with more margin.** DINOv2 misses one photo, a same-art reprint, and still has it at rank 2. CLIP misses two: Blastoise ex at rank 2 behind a different Blastoise ex, and Prismatic Evolutions Vaporeon, which isn't in its top 3 at all. Among CLIP's top-3 for that Vaporeon is an Arctibax.
- **It matches the picture, not the "concept".** CLIP is trained to align images with text, so it groups cards by theme ("blue water Pokémon"). DINOv2 is self-supervised on visual similarity and keeps the fine detail of the artwork.
- **Cost is acceptable.** DINOv2 is ~0.18 s slower per photo than CLIP and its index is larger (58 MB vs 19 MB for 4,742 cards). Neither matters at this scale.

### What changed since the 20-photo run: artwork embedding

Each card is now embedded twice: the whole card, and the **artwork box** (the illustration area, `ART_BOX` in `scanner/embedders.py`). The two vectors are weighted 50/50 (`ART_WEIGHT`) and concatenated. Reverse-holo foil, promo stamps and imperfect crops change the rest of the card but not the artwork. The comparison below counts all 44 photos, catalog gaps included:

| DINOv2, 44 photos | top-1 | top-3 |
|---|---|---|
| whole card only | 84.1% | 93.2% |
| whole card + artwork | 90.9% | 93.2% |

It fixed Wimpod, Gengar and the Prismatic Evolutions Vaporeon, which had been at rank 2.

## Where it fails

### Wrong card (DINOv2)

| photo | expected | result | kind |
|---|---|---|---|
| `sv03.5-004` | Charmander, 151 #004 | rank 2, behind `sv04.5-007` Charmander (Paldean Fates) | **Same-art reprint**: the image model narrows it down to the right artwork; only the set code and number tell them apart |

Same-art reprints (Paldean Fates, Prismatic Evolutions, Shrouded Fable, promo reprints of set cards) need the set code and number from **OCR, planned for Phase 1**. OCR can then pick from the image model's top 3.

### Catalog gaps (not scored)

| photo | card | why it can't be matched |
|---|---|---|
| `mee-010` | Basic Fire Energy, MEE 010, 30th stamp (2026) | TCGdex's `mee` set lists only 001–008, all without images |
| `mee-014` | Basic Fighting Energy, MEE 014, 30th stamp (2026) | same |
| `mep-078` | Toxel, MEP promo | TCGdex has the card but no image |

The Phase 0 catalog has 250 cards without an image on TCGdex: every card in MEP (89), SVE energies (24), MEE energies (8), 30th Classic Collection (30), My First Battle (34) and both McDonald's sets (15 + 15), plus 34 SVP promos and 1 card from 151. pokemontcg.io doesn't have the MEE or MEP sets either, so it can't fill the gap. Options for later: shop-taken reference photos for gap cards, or wait for TCGdex to add images.

### Hard photos that still matched

- **Binders and 9-pocket pages**: the crop sometimes includes the pocket rim or cuts off the top of the card. These photos still matched (Sylveon, Mega Floette, Blastoise).
- **Sleeves with glare**, holo and full-art foil: no misses.
- **Card lying sideways or upside down**: the crop rotates it upright. Search also tries the crop rotated 180° and keeps the best score per card.
- **Busy backgrounds** (playmat art, other objects on the table): handled by the region-based crop.

## Other findings

- **Spanish cards** (2 photos, `photos/es/`): both match their English printing at rank 1 with both models, because the artwork is shared. The language itself will have to come from OCR.
- **Crop:** an edge-only contour detector didn't work on real photos. The card outline merged with playmat art and binder pockets, and sleeve edges often left one side without a visible edge. The crop uses GrabCut instead, which separates the card from the background as a region. The outline of that region gives the 4 corners, and the card is then straightened. It found a card in 44/44 photos. See `scanner/crop.py`.
- **Timing:** each photo goes through HEIC decode, crop, embedding of 4 images (upright and rotated 180°, each as whole card and artwork), and a FAISS search (~2 ms). In the app the phone will send a downscaled JPEG, which removes most of the decode time.
- **macOS only:** the torch and faiss-cpu wheels each ship their own OpenMP runtime, and `scripts/eval.py` aborts with `OMP: Error #15`. On a Mac, run it with `KMP_DUPLICATE_LIB_OK=TRUE`. Linux and Windows shop PCs shouldn't need this.

## QA gate

| item | result | evidence |
|---|---|---|
| [AUTO] English: correct card 1st in ≥ 85% of real photos | **PASS** | DINOv2 97.6% (40/41 scored photos; 3 catalog gaps reported separately) |
| [AUTO] English: correct card in top 3 in ≥ 95% | **PASS** | DINOv2 100% (41/41) |
| [AUTO] Each search < 2 s on CPU | **PASS on dev machine · NEEDS MANUAL CHECK on shop PC** | slowest photo 0.78 s with 4 torch threads on an Apple M5. A typical shop PC is slower, so time it there |
| [AUTO] This document records the winner, why, and the failing photos | **PASS** | this file |

## Setup used

- **Catalog:** TCGdex English, every set released since 2023-03-01 (all of Scarlet & Violet, Mega Evolution, promos, energies, 30th Celebration). 31 sets; 4,742 cards with images, 250 without. TCG Pocket excluded.
- **Models:** `open_clip` ViT-B-32-quickgelu with `openai` weights, and `facebook/dinov2-base` (CLS + mean patch token). Inputs are squashed to 224×224, as whole card + artwork box.
- **Index:** `faiss.IndexFlatIP` over L2-normalized vectors (exact cosine search).
- **Machine:** Apple M5 (10 cores), torch limited to 4 threads, no GPU. torch 2.14.1, faiss-cpu 1.15.1, open_clip 3.3.0, transformers 5.19.0. **Not yet measured on the shop PC.**
- **Photos:** 44 English (`photos/en/`), 2 Spanish (`photos/es/`), 3 older cards outside the catalog (`photos/en-out-of-scope/`). All are named `<tcgdex id>.heic` except the out-of-scope ones.

## Next

1. Time `scripts/eval.py --threads 4` on the shop PC.
2. Phase 1: OCR of the set code and number to break same-art reprint ties among DINOv2's top 3.
3. Decide how to handle catalog-gap cards: manual entry, or shop-taken reference photos.
