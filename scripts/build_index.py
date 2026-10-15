"""Embed every catalog image with one model and save a FAISS index for it.

Usage:
    python scripts/build_index.py --model dinov2            # whole catalog (~35 min on a laptop CPU)
    python scripts/build_index.py --model dinov2 --append   # only cards not in the index yet

Writes data/index/<model>_<lang>.faiss and data/index/<model>_<lang>_ids.json.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import torch
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from server.recognition import index as faiss_index  # noqa: E402
from server.recognition.embedders import MODELS, embed_cards, load_embedder  # noqa: E402


def read_catalog(path: Path) -> list[dict]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return sorted(rows, key=lambda r: r["id"])


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", choices=MODELS, required=True)
    ap.add_argument("--lang", choices=("en", "es", "ja"), default="en")
    ap.add_argument("--catalog", type=Path, help="default: data/catalog_<lang>.jsonl")
    ap.add_argument("--index-dir", type=Path, default=ROOT / "data" / "index")
    ap.add_argument("--batch-size", type=int, default=32)
    ap.add_argument("--threads", type=int, default=0, help="torch CPU threads (0 = default)")
    ap.add_argument("--append", action="store_true",
                    help="add only catalog cards missing from the existing index (after fill_image_gaps.py)")
    args = ap.parse_args(argv)

    if args.threads:
        torch.set_num_threads(args.threads)
    args.catalog = args.catalog or ROOT / "data" / f"catalog_{args.lang}.jsonl"
    rows = read_catalog(args.catalog)
    print(f"{len(rows)} cards in {args.catalog}")
    existing = None
    if args.append and faiss_index.index_paths(args.index_dir, args.model, args.lang)[0].exists():
        existing = faiss_index.load(args.index_dir, args.model, args.lang)
        indexed = set(existing[1])
        rows = [r for r in rows if r["id"] not in indexed]
        print(f"{len(indexed)} already indexed; {len(rows)} to add")
        if not rows:
            return 0
    embedder = load_embedder(args.model)

    ids: list[str] = []
    chunks: list[np.ndarray] = []
    t0 = time.perf_counter()
    for start in range(0, len(rows), args.batch_size):
        batch = rows[start : start + args.batch_size]
        images = []
        for r in batch:
            with Image.open(ROOT / r["image_path"]) as im:
                images.append(im.convert("RGB"))
        chunks.append(embed_cards(embedder, images))
        ids.extend(r["id"] for r in batch)
        done = start + len(batch)
        rate = done / (time.perf_counter() - t0)
        print(f"  {done}/{len(rows)}  ({rate:.1f} img/s)", end="\r", flush=True)
    print()

    vectors = np.concatenate(chunks)
    if existing is not None:
        idx, old_ids = existing
        if idx.d != vectors.shape[1]:
            print(f"index has {idx.d}-dim vectors but the model gives {vectors.shape[1]}; rebuild without --append",
                  file=sys.stderr)
            return 1
        idx.add(np.ascontiguousarray(vectors, dtype=np.float32))
        ids = old_ids + ids
    else:
        idx = faiss_index.build(vectors)
    faiss_index.save(idx, ids, args.index_dir, args.model, args.lang)
    print(f"saved {idx.ntotal} x {vectors.shape[1]} vectors to "
          f"{faiss_index.index_paths(args.index_dir, args.model, args.lang)[0]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
