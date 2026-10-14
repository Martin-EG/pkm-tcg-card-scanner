# Phase 0 — Identification proof of concept: results

Oct 14, 2026 · image only, no OCR

## Verdict

**DINOv2 wins.** On 20 real English counter photos it ranks the correct card 1st in 90% (18/20) and in the top 3 in 95% (19/20), with every search under 1.2 s on a 4-core CPU. CLIP gets 75% / 80% on the same photos.

| model | photos | top-1 | top-3 | mean s | max s | card found |
|---|---|---|---|---|---|---|
| CLIP ViT-B/32 (OpenAI) | 20 | 75.0% | 80.0% | 0.778 | 1.143 | 100% |
| **DINOv2 ViT-B/14** | 20 | **90.0%** | **95.0%** | 0.840 | 1.167 | 100% |

Source: `python scripts/eval.py --photos photos/en` (full output in `reports/phase0_eval_en.txt`, per-photo detail in `reports/phase0_eval.json`).

**Caveat — small sample.** 20 photos, not the 50 the plan calls for. The 95% confidence interval for 18/20 is roughly 70–97%, so the 85% target is met on this sample but not yet proven. Re-run the same command once there are 50 photos.

## Why DINOv2 won

- **It matches the picture, not the "concept".** CLIP is trained to align images with text, so it groups cards by theme ("blue water Pokémon", "colorful ex card"). Its misses were plausible-looking but wrong cards: Blastoise ex → Ogerpon ex, Sylveon ex → Charizard ex. DINOv2 is self-supervised on visual similarity and keeps the fine details of the artwork, which is what tells two printings apart.
- **It has margin.** When DINOv2 is right, the right card is usually clearly ahead. When CLIP is right, the top candidates are often within 0.01 of each other.
- **It tolerates bad crops.** Binder shots that cut off part of the card still matched with DINOv2. CLIP lost 2 photos (from 90% to 80% top-3) just from a small change in crop size.
- **Cost is similar.** End to end, CLIP takes 0.78 s per photo on average and DINOv2 0.84 s. DINOv2's embedding is ~0.13 s per view, and search is ~2 ms over 4,742 cards. DINOv2's index is larger (28 MB vs 9 MB), which doesn't matter at this scale.

## Where it fails (DINOv2)

| photo | expected | result | kind |
|---|---|---|---|
| `mep-078` | Toxel, MEP promo | not in index | **Catalog gap**: TCGdex has the card but no image (89 of the MEP promos have no image) |
| `sv08.5-022` | Vaporeon, Prismatic Evolutions 022/131 | rank 2, behind `sv03.5-134` | **Same-art reprint**: PRE reuses the exact 151 artwork; only the set code and number differ (score gap 0.001) |

Neither failure can be fixed with a better image model:

- **Same-art reprints** (PRE, Shrouded Fable, Paldean Fates and promo reprints of set cards) need the set code and number, which is the OCR step planned for Phase 1. The image model already narrows it down to the right artwork.
- **Catalog gaps** need another image source, or a fallback where the employee enters the card by hand. The Phase 0 catalog has 250 cards without images, mostly MEP/SVP promos and 30th Celebration.

### Photos that are hard but still matched

- **Binders and 9-pocket pages**: the crop sometimes includes the pocket rim or cuts off the top of the card (Sylveon, Mega Floette, Blastoise, Vaporeon). DINOv2 still matched all except the same-art Vaporeon. Pulling the card out of the binder for the photo will help.
- **Sleeves with glare** and holo/full-art foil: no misses in this sample.
- **Card lying sideways** (Typhlosion): the crop rotates it upright. Search also tries the crop rotated 180°, in case it comes out upside down. That made no difference on these 20 photos but costs only ~0.05 s.
- **Busy backgrounds** (playmat with art, money on the table): handled by the region-based crop.

## Other findings

- **Spanish cards** (2 photos, `photos/es/`): both matched their English printing at rank 1 with both models, because the artwork is shared. That's encouraging for "Spanish via the English index". The language itself still has to come from OCR.
- **Crop:** an edge-only contour detector didn't work on real photos. The card outline merged with playmat art and binder pockets, and sleeve edges often leave one side without a visible edge. The crop now uses GrabCut, which separates the card from the background as a region; the outline of that region gives the four corners, which are then straightened. It finds a card in 20/20 photos, taking 0.15–0.6 s at a 256 px working size. See `scanner/crop.py`.
- **Timing breakdown** (DINOv2, per photo): HEIC decode ~0.3 s · crop 0.15–0.6 s · embedding of 2 views ~0.25 s · FAISS search ~2 ms. In the app, the phone will send a downscaled JPEG, which removes most of the decode time.

## Setup used

- Catalog: TCGdex English, every set released since 2023-03-01 (all of Scarlet & Violet, Mega Evolution, promos, 30th Celebration). 31 sets, 4,742 cards with images. TCG Pocket excluded.
- Models: `open_clip` ViT-B-32-quickgelu / `openai` weights; `facebook/dinov2-base` (CLS + mean patch token). Both read the whole card squashed to 224×224.
- Index: `faiss.IndexFlatIP` over L2-normalized vectors (exact cosine search).
- Machine: cloud VM, 4 vCPU Intel Xeon @ 2.1 GHz, no GPU, torch 2.14. **Not yet measured on the shop PC.**
- Photos: 20 English (`photos/en/`), 2 Spanish (`photos/es/`), 3 older cards outside the catalog (`photos/en-out-of-scope/`: 2004 EX Deoxys, 2010 HGSS promo, 2022 Silver Tempest), all named `<tcgdex id>.heic`.

## Next

1. Take 30 more English counter photos and re-run `scripts/eval.py` to confirm 85% / 95% at n = 50.
2. Phase 1: OCR of the set code and number to break same-art reprint ties among DINOv2's top-k.
3. Time a search on the shop PC.
