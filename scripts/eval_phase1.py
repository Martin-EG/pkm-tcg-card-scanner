"""Phase 1 QA gate: run the identification service end to end and report each gate item.

Usage:
    python scripts/eval_phase1.py --threads 4

Items:
  1. Top-1 on the Phase 0 photos (photos/en) >= Phase 0 (97.6% on cards in the index).
  2. A 9-card binder page in under 10 s: real pages in photos/binder (any card count)
     and a synthetic page built from 9 catalog images.
  3. Same-art reprints told apart by collector number: real photos in photos/en whose
     card has a same-name, same-art reprint, plus synthetic cases (degraded catalog
     images of same-art pairs found in the catalog).
  4. No card / blurry photo -> clear error: photos/binder/IMG_3771 (empty page),
     photos/binder/IMG_3772 (blurry), and photos/errors/* if present.
  5. Only English results with ENABLE_SPANISH and ENABLE_JAPANESE false; Spanish
     photos (photos/es) are flagged as Spanish.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import torch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from server.recognition.crop import PhotoError, find_card_quad, warp_card  # noqa: E402
from scripts.evaluation import card_id_from_filename, list_photos  # noqa: E402
from server.recognition.identify import Identifier  # noqa: E402
from scripts.eval import load_photo  # noqa: E402

PHASE0_TOP1 = 0.976
PAGE_SECONDS = 10.0
REPRINT_TARGET = 9  # of 10
EMPTY_PAGE = "IMG_3771.HEIC"
BLURRY_PAGE = "IMG_3772.HEIC"


def item1_phase0(ident: Identifier, photos_dir: Path) -> dict:
    indexed = set(ident.catalogs["en"].rows)
    rows, scored = [], 0
    top1 = top3 = 0
    for p in list_photos(photos_dir):
        true_id = card_id_from_filename(p)
        t0 = time.perf_counter()
        try:
            cards = ident.identify_photo(load_photo(p))
            preds = [c.card_id for c in cards[0].candidates]
            langs = sorted({c.lang for r in cards for c in r.candidates})
            ocr = cards[0].ocr_used
            review = cards[0].needs_review
            error = None
        except PhotoError as e:
            preds, langs, ocr, review, error = [], [], False, False, e.code
        secs = time.perf_counter() - t0
        gap = true_id not in indexed
        rank = preds.index(true_id) + 1 if true_id in preds else None
        if not gap:
            scored += 1
            top1 += rank == 1
            top3 += rank is not None and rank <= 3
        rows.append({"photo": p.name, "true": true_id, "gap": gap, "rank": rank, "top3": preds, "langs": langs, "needs_review": review,
                     "ocr": ocr, "error": error, "seconds": round(secs, 3)})
    return {"scored": scored, "top1": top1 / scored if scored else 0, "top3": top3 / scored if scored else 0,
            "max_seconds": max(r["seconds"] for r in rows), "rows": rows}


def synthetic_page(paths: list[Path], card_h: int = 620, seed: int = 0) -> np.ndarray:
    """9 catalog images in a 3x3 binder-like grid on a dark page, slightly rotated."""
    rng = np.random.default_rng(seed)
    card_w = int(card_h * 63 / 88)
    gap, margin = 50, 80
    W, H = margin * 2 + 3 * card_w + 2 * gap, margin * 2 + 3 * card_h + 2 * gap
    page = np.full((H, W, 3), (38, 36, 40), np.uint8)
    page = cv2.add(page, rng.integers(0, 14, page.shape, dtype=np.uint8))
    for k, path in enumerate(paths):
        r, c = divmod(k, 3)
        card = cv2.resize(_read_card(path), (card_w, card_h), interpolation=cv2.INTER_AREA)
        x, y = margin + c * (card_w + gap), margin + r * (card_h + gap)
        page[y:y + card_h, x:x + card_w] = card
    m = cv2.getRotationMatrix2D((W / 2, H / 2), float(rng.uniform(-3, 3)), 1.0)
    return cv2.warpAffine(page, m, (W, H), borderValue=(38, 36, 40))


def _read_card(path: Path) -> np.ndarray:
    from PIL import Image

    with Image.open(path) as im:
        return cv2.cvtColor(np.asarray(im.convert("RGB")), cv2.COLOR_RGB2BGR)


def item2_pages(ident: Identifier, binder_dir: Path) -> dict:
    out = {"real": [], "synthetic": []}
    for p in list_photos(binder_dir):
        if p.name in (EMPTY_PAGE, BLURRY_PAGE):
            continue
        t0 = time.perf_counter()
        cards = ident.identify_photo(load_photo(p))
        secs = time.perf_counter() - t0
        out["real"].append({"photo": p.name, "cards": len(cards), "seconds": round(secs, 3),
                            "ocr_cards": sum(c.ocr_used for c in cards),
                            "langs": sorted({c.lang for r in cards for c in r.candidates}),
                            "top1": [(c.candidates[0].card_id, c.candidates[0].name, c.candidates[0].visual_score,
                                      c.foreign_language, c.needs_review) for c in cards]})
    cat = ident.catalogs["en"]
    rng = np.random.default_rng(7)
    ids = sorted(cat.rows)
    for seed in range(3):
        chosen = [ids[i] for i in rng.choice(len(ids), 9, replace=False)]
        page = synthetic_page([ROOT / cat.rows[i]["image_path"] for i in chosen], seed=seed)
        t0 = time.perf_counter()
        cards = ident.identify_photo(page)
        secs = time.perf_counter() - t0
        got = [c.candidates[0].card_id for c in cards]
        out["synthetic"].append({"cards": len(cards), "seconds": round(secs, 3), "correct": sum(
            a == b for a, b in zip(got, chosen)), "ocr_cards": sum(c.ocr_used for c in cards)})
    out["max_seconds"] = max(r["seconds"] for r in out["real"] + out["synthetic"])
    return out


def same_art_pairs(ident: Identifier, n: int, min_sim: float = 0.97) -> list[tuple[str, str, float]]:
    """Same-name cards in different sets whose catalog images embed almost identically."""
    import faiss

    index, ids = ident.indexes["en"]
    rows = ident.catalogs["en"].rows
    by_name: dict[str, list[int]] = {}
    for i, cid in enumerate(ids):
        by_name.setdefault(rows[cid]["name"], []).append(i)
    vecs = index.reconstruct_n(0, index.ntotal)
    pairs = []
    for name, idxs in by_name.items():
        if len(idxs) < 2:
            continue
        sims = vecs[idxs] @ vecs[idxs].T
        for a in range(len(idxs)):
            for b in range(a + 1, len(idxs)):
                ca, cb = ids[idxs[a]], ids[idxs[b]]
                if rows[ca]["set"] != rows[cb]["set"] and sims[a, b] >= min_sim:
                    pairs.append((ca, cb, float(sims[a, b])))
    pairs.sort(key=lambda t: -t[2])
    # One pair per name, spread over eras.
    seen, out = set(), []
    for a, b, s in pairs:
        if rows[a]["name"] in seen:
            continue
        seen.add(rows[a]["name"])
        out.append((a, b, s))
    step = max(1, len(out) // n)
    del faiss
    return out[::step][:n]


def degrade(card: np.ndarray, seed: int) -> np.ndarray:
    """Phone-like copy of a catalog image: perspective, slight blur, JPEG, on a table."""
    rng = np.random.default_rng(seed)
    h, w = card.shape[:2]
    W, H = int(w * 1.5), int(h * 1.4)
    photo = np.full((H, W, 3), (70, 90, 80), np.uint8)
    photo = cv2.add(photo, rng.integers(0, 20, photo.shape, dtype=np.uint8))
    src = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
    jitter = rng.uniform(-0.03, 0.03, (4, 2)) * [w, h]
    dst = (src + [(W - w) / 2, (H - h) / 2] + jitter).astype(np.float32)
    m = cv2.getPerspectiveTransform(src, dst)
    warped = cv2.warpPerspective(card, m, (W, H))
    mask = cv2.warpPerspective(np.full((h, w), 255, np.uint8), m, (W, H))
    photo[mask > 0] = warped[mask > 0]
    photo = cv2.GaussianBlur(photo, (0, 0), 0.8)
    return cv2.imdecode(cv2.imencode(".jpg", photo, [cv2.IMWRITE_JPEG_QUALITY, 85])[1], cv2.IMREAD_COLOR)


def item3_reprints(ident: Identifier, phase0_rows: list[dict]) -> dict:
    rows_en = ident.catalogs["en"].rows
    real = []
    for r in phase0_rows:
        if r["gap"] or not r["top3"]:
            continue
        name = rows_en[r["true"]]["name"]
        if any(c != r["true"] and rows_en.get(c, {}).get("name") == name for c in r["top3"]):
            real.append({"photo": r["photo"], "true": r["true"], "rank": r["rank"], "ocr": r["ocr"]})
    synthetic = []
    pairs = same_art_pairs(ident, 5)
    for k, (a, b, sim) in enumerate(pairs):
        for true_id, other in ((a, b), (b, a)):
            photo = degrade(_read_card(ROOT / rows_en[true_id]["image_path"]), seed=k)
            try:
                # Reprint discrimination only: skip the blur gate, which the clean synthetic
                # photo can trip (it has none of a real photo's texture).
                quad = find_card_quad(photo)
                if quad is None:
                    raise PhotoError("no_card", "")
                cards = ident.identify_cards([warp_card(photo, quad)])
                preds = [c.card_id for c in cards[0].candidates]
                text = cards[0].text
                read = sorted(text.numbers) + sorted(text.set_codes) if text else []
            except PhotoError as e:
                preds, read = [], [e.code]
            synthetic.append({"true": true_id, "reprint": other, "similarity": round(sim, 4),
                              "top1": preds[0] if preds else None, "correct": bool(preds) and preds[0] == true_id,
                              "ocr_read": read})
    return {"real": real, "synthetic": synthetic,
            "synthetic_correct": sum(s["correct"] for s in synthetic), "synthetic_n": len(synthetic)}


def item4_errors(ident: Identifier, binder_dir: Path, errors_dir: Path) -> list[dict]:
    cases = [(binder_dir / EMPTY_PAGE, "no_card"), (binder_dir / BLURRY_PAGE, "blurry")]
    if errors_dir.exists():
        cases += [(p, None) for p in list_photos(errors_dir)]
    out = []
    for path, want in cases:
        if not path.exists():
            continue
        try:
            cards = ident.identify_photo(load_photo(path))
            got = f"{len(cards)} card(s): " + ", ".join(c.candidates[0].card_id for c in cards)
            ok = False
        except PhotoError as e:
            got, ok = e.code, want is None or e.code == want
        out.append({"photo": str(path.relative_to(ROOT)), "expected": want or "error", "got": got, "pass": ok})
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--threads", type=int, default=4)
    ap.add_argument("--report", type=Path, default=ROOT / "reports" / "phase1_eval.json")
    args = ap.parse_args(argv)
    torch.set_num_threads(args.threads)

    ident = Identifier(("en",))  # ENABLE_SPANISH / ENABLE_JAPANESE false
    ident.identify_cards([np.zeros((880, 630, 3), np.uint8)])  # warm-up, not timed
    ident.reader._engine()
    ident.reader._engine("name_recognition_model")

    r1 = item1_phase0(ident, ROOT / "photos" / "en")
    r2 = item2_pages(ident, ROOT / "photos" / "binder")
    r3 = item3_reprints(ident, r1["rows"])
    r4 = item4_errors(ident, ROOT / "photos" / "binder", ROOT / "photos" / "errors")
    langs = {lang for r in r1["rows"] + r2["real"] for lang in r["langs"] if lang != "en"}
    flagged = []
    for p in list_photos(ROOT / "photos" / "es"):
        try:
            card = ident.identify_photo(load_photo(p))[0]
            flagged.append({"photo": p.name, "flag": card.foreign_language,
                            "top1": card.candidates[0].card_id, "read": card.text.raw if card.text else []})
        except PhotoError as e:
            flagged.append({"photo": p.name, "flag": None, "top1": e.code, "read": []})

    print(f"1. Phase 0 photos: top-1 {r1['top1']:.1%}  top-3 {r1['top3']:.1%}  ({r1['scored']} scored)  "
          f"max {r1['max_seconds']:.2f}s  marked for review: "
          f"{sum(r['needs_review'] for r in r1['rows'] if not r['gap'])}")
    for r in r1["rows"]:
        if not r["gap"] and r["rank"] != 1:
            print(f"   miss {r['photo']}: rank {r['rank']} top3 {r['top3']} ocr={r['ocr']} {r['error'] or ''}")
    print("2. Pages:")
    for r in r2["real"]:
        print(f"   {r['photo']}: {r['cards']} cards in {r['seconds']:.2f}s (OCR on {r['ocr_cards']})")
        for cid, name, score, flag, review in r["top1"]:
            print(f"      {cid} {name} ({score:.3f}){' flag=' + flag if flag else ''}{' REVIEW' if review else ''}")
    for r in r2["synthetic"]:
        print(f"   synthetic 9-card page: {r['cards']} cards, {r['correct']}/9 correct, {r['seconds']:.2f}s "
              f"(OCR on {r['ocr_cards']})")
    print("3. Same-art reprints:")
    for r in r3["real"]:
        print(f"   real {r['photo']}: rank {r['rank']} ocr={r['ocr']}")
    for r in r3["synthetic"]:
        print(f"   synthetic {r['true']} vs {r['reprint']} (sim {r['similarity']}): top1 {r['top1']} "
              f"{'OK' if r['correct'] else 'WRONG'}  read {r['ocr_read']}")
    print(f"   synthetic correct: {r3['synthetic_correct']}/{r3['synthetic_n']}")
    print("4. Errors:")
    for r in r4:
        print(f"   {r['photo']}: expected {r['expected']}, got {r['got']} -> {'PASS' if r['pass'] else 'FAIL'}")
    print(f"5. Languages other than English in results: {sorted(langs) or 'none'}")
    for f in flagged:
        print(f"   {f['photo']}: flagged {f['flag']}, top1 {f['top1']}, read {f['read']}")

    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps({"item1": r1, "item2": r2, "item3": r3, "item4": r4,
                                       "non_english": sorted(langs), "spanish_flags": flagged}, indent=1, ensure_ascii=False, default=str))
    print(f"report: {args.report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
