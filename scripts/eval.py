"""Evaluate image-only identification on real phone photos.

Each photo is named after its correct TCGdex card id, e.g. sv06-123.jpg
(extra shots of the same card: sv06-123_2.jpg).

Usage:
    python scripts/eval.py --photos photos
    python scripts/eval.py --photos photos --models dinov2 --save-crops

For every model: crop the card, embed it, search the index, and report top-1 and
top-3 accuracy, time per search on CPU (decode + crop + embed + search), and failures.
Photos of cards the index has no image for (catalog gaps) are listed separately and
left out of top-1/top-3; they still count toward timing.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict
from pathlib import Path

import cv2
import numpy as np
import torch
from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scanner import index as faiss_index  # noqa: E402
from scanner.crop import crop_card  # noqa: E402
from scanner.embedders import MODELS, embed_cards, load_embedder  # noqa: E402
from scanner.evaluation import Result, Summary, card_id_from_filename, list_photos, summarize  # noqa: E402

try:  # iPhone photos
    from pillow_heif import register_heif_opener

    register_heif_opener()
except ImportError:
    pass

TOP_K = 3
# How many index hits to fetch before merging the two orientations.
SEARCH_K = 10


def load_photo(path: Path) -> np.ndarray:
    """Read a photo as BGR, applying the phone's EXIF rotation."""
    with Image.open(path) as im:
        im = ImageOps.exif_transpose(im).convert("RGB")
        return cv2.cvtColor(np.asarray(im), cv2.COLOR_RGB2BGR)


def identify(photo_path: Path, embedder, index, ids, flip: bool) -> tuple[list[tuple[str, float]], bool, np.ndarray]:
    bgr = load_photo(photo_path)
    card, found = crop_card(bgr)
    pil = Image.fromarray(cv2.cvtColor(card, cv2.COLOR_BGR2RGB))
    views = [pil, pil.rotate(180)] if flip else [pil]
    vectors = embed_cards(embedder, views)
    best: dict[str, float] = {}
    for v in vectors:
        for cid, score in faiss_index.search(index, ids, v, SEARCH_K):
            best[cid] = max(score, best.get(cid, -1.0))
    ranked = sorted(best.items(), key=lambda kv: kv[1], reverse=True)[:TOP_K]
    return ranked, found, card


def read_names(catalog: Path) -> dict[str, str]:
    names = {}
    for line in catalog.read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            names[r["id"]] = r["name"]
    return names


def print_summary(s: Summary, names: dict[str, str]) -> None:
    print(f"\n=== {s.model}: {s.n} photos scored, {len(s.gaps)} catalog gaps ===")
    print(f"top-1 {s.top1:.1%}   top-3 {s.top3:.1%}   mean {s.mean_seconds:.3f}s   max {s.max_seconds:.3f}s   "
          f"card found {s.crop_rate:.0%}")
    for title, rows in (("failures", s.failures), ("catalog gaps, not scored", s.gaps)):
        if not rows:
            continue
        print(f"{title} (photo | expected | rank | top-3):")
        for f in rows:
            crop = "" if f.cropped else "  [no card found, used full photo]"
            top = ", ".join(f"{cid} {names.get(cid, '?')} ({sc:.3f})" for cid, sc in f.predictions)
            print(f"  {f.photo} | {f.true_id} {names.get(f.true_id, '?')} | {f.rank() or '-'} | {top}{crop}")


def print_table(summaries: list[Summary]) -> None:
    header = f"| {'model':<8} | {'photos':>6} | {'gaps':>4} | {'top-1':>6} | {'top-3':>6} | {'mean s':>7} | {'max s':>6} | {'card found':>10} |"
    print("\n" + header)
    print("|" + "|".join("-" * (len(c)) for c in header.split("|")[1:-1]) + "|")
    for s in summaries:
        print(f"| {s.model:<8} | {s.n:>6} | {len(s.gaps):>4} | {s.top1:>6.1%} | {s.top3:>6.1%} | {s.mean_seconds:>7.3f} | "
              f"{s.max_seconds:>6.3f} | {s.crop_rate:>10.0%} |")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--photos", type=Path, required=True)
    ap.add_argument("--models", nargs="+", choices=MODELS, default=list(MODELS))
    ap.add_argument("--index-dir", type=Path, default=ROOT / "data" / "index")
    ap.add_argument("--catalog", type=Path, default=ROOT / "data" / "catalog_en.jsonl")
    ap.add_argument("--report", type=Path, default=ROOT / "reports" / "phase0_eval.json")
    ap.add_argument("--save-crops", action="store_true", help="write cropped cards to reports/crops/")
    ap.add_argument("--no-flip", dest="flip", action="store_false",
                    help="search only the upright crop (default also searches it rotated 180°)")
    ap.add_argument("--threads", type=int, default=0, help="torch CPU threads (0 = default)")
    args = ap.parse_args(argv)

    if args.threads:
        torch.set_num_threads(args.threads)
    photos = list_photos(args.photos)
    if not photos:
        print(f"no photos found in {args.photos}", file=sys.stderr)
        return 1
    names = read_names(args.catalog)
    print(f"{len(photos)} photos, CPU threads: {torch.get_num_threads()}, flip: {args.flip}")

    summaries: list[Summary] = []
    report: dict = {"photos": len(photos), "flip": args.flip, "models": {}}
    for model in args.models:
        embedder = load_embedder(model)
        index, ids = faiss_index.load(args.index_dir, model)
        identify(photos[0], embedder, index, ids, args.flip)  # warm-up, not timed
        results: list[Result] = []
        for p in photos:
            t0 = time.perf_counter()
            preds, found, card = identify(p, embedder, index, ids, args.flip)
            elapsed = time.perf_counter() - t0
            results.append(Result(p.name, card_id_from_filename(p), preds, elapsed, found))
            if args.save_crops:
                out = args.report.parent / "crops" / f"{p.stem}.jpg"
                out.parent.mkdir(parents=True, exist_ok=True)
                cv2.imwrite(str(out), card)
        s = summarize(model, results, indexed=set(ids))
        summaries.append(s)
        print_summary(s, names)
        report["models"][model] = {
            **{k: v for k, v in asdict(s).items() if k not in ("failures", "gaps")},
            "catalog_gaps": [g.true_id for g in s.gaps],
            "results": [{**asdict(r), "rank": r.rank()} for r in results],
        }

    print_table(summaries)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=1, ensure_ascii=False))
    print(f"\nreport: {args.report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
