"""Fill the catalog's image gaps with pokemontcg.io images.

TCGdex lists some cards without an image (whole sets like Shining Legends or the
Trainer Galleries, many promos), so fetch_catalog.py leaves them out and they can't
be recognized. pokemontcg.io has images for many of them. This script finds every
TCGdex card that has no image, maps it to pokemontcg.io (set mapping in
server/pricing/setmap.py), downloads the large image, stores it like the TCGdex ones
(600x825 webp), and appends the card to data/catalog_en.jsonl with
"image_source": "pokemontcg".

Usage:
    python scripts/fill_image_gaps.py              # then: python scripts/build_index.py --model dinov2 --append
    python scripts/fill_image_gaps.py --dry-run    # only count the gaps
    python scripts/fill_image_gaps.py --retry      # also retry cards that weren't found last time

Safe to interrupt and re-run: cards already in the catalog are skipped, and cards
pokemontcg.io doesn't have are remembered in data/cache/image_gaps_en.json.
"""

from __future__ import annotations

import argparse
import io
import json
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from typing import Callable
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.fetch_catalog import (  # noqa: E402
    USER_AGENT, RateLimiter, TcgdexClient, load_done, load_set_dates, select_sets, with_retries,
)
from server.pricing.setmap import build_set_map  # noqa: E402

CDN = "https://images.pokemontcg.io"
# Same size as TCGdex's "high" images, so both sources embed alike.
SIZE = (600, 825)
LANG = "en"


def image_url(ptcg_set: str, number: str) -> str:
    """pokemontcg.io large image: digits lose leading zeros ("004" -> "4"),
    other numbers keep their form ("TG01", "HGSS21", "RC1")."""
    number = number.strip()
    if number.isdigit():
        number = str(int(number))
    return f"{CDN}/{ptcg_set}/{number}_hires.png"


def fetch_bytes(url: str, timeout: float = 30.0) -> bytes | None:
    """The file, or None when it doesn't exist (404)."""
    try:
        with urlopen(Request(url, headers={"User-Agent": USER_AGENT}), timeout=timeout) as r:
            return r.read()
    except HTTPError as e:
        if e.code == 404:
            return None
        raise


def to_webp(data: bytes, dest: Path) -> None:
    with Image.open(io.BytesIO(data)) as im:
        im = im.convert("RGBA").resize(SIZE, Image.LANCZOS)
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(".part")
        im.save(tmp, "WEBP", quality=90)
        tmp.replace(dest)  # atomic: a half-written file never looks finished


def find_gaps(client, set_ids: list[str], done: set[str], limiter: RateLimiter) -> list[tuple[str, dict, dict]]:
    """(set id, set, card) for every card TCGdex lists without an image and that isn't
    in the catalog yet."""
    gaps = []
    for set_id in set_ids:
        s = with_retries(lambda: client.get_set(set_id), limiter)
        for card in s.get("cards", []):
            if card["id"] not in done and not card.get("image"):
                gaps.append((set_id, s, card))
    return gaps


def fill(gaps: list[tuple[str, dict, dict]], set_map: dict[str, str], data_dir: Path, catalog_path: Path,
         misses: dict[str, str], limiter: RateLimiter, download: Callable[[str], bytes | None] = fetch_bytes,
         workers: int = 4) -> Counter:
    """Download what pokemontcg.io has; append catalog rows; record misses. Returns counts."""
    counts: Counter = Counter()

    def one(gap):
        set_id, s, card = gap
        ptcg_set = set_map.get(set_id)
        if not ptcg_set:
            return gap, "no_mapping", None
        limiter.wait()
        data = download(image_url(ptcg_set, card["localId"]))
        if data is None:
            return gap, "not_found", None
        dest = (data_dir / "images" / LANG / set_id / f"{card['id']}.webp").resolve()
        to_webp(data, dest)
        return gap, "filled", dest

    with catalog_path.open("a", encoding="utf-8") as out, ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        # Rows are written from this thread only, as each download finishes.
        for (set_id, s, card), status, dest in pool.map(one, gaps):
            counts[status] += 1
            counts[f"{status}:{set_id}"] += 1
            if status != "filled":
                misses[card["id"]] = status
                continue
            misses.pop(card["id"], None)
            row = {
                "id": card["id"], "name": card["name"], "set": set_id, "set_name": s["name"],
                "number": card["localId"], "language": LANG,
                "image_path": str(dest.relative_to(ROOT)) if dest.is_relative_to(ROOT) else str(dest),
                "image_source": "pokemontcg",
            }
            out.write(json.dumps(row, ensure_ascii=False) + "\n")
            out.flush()
    return counts


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-dir", type=Path, default=ROOT / "data")
    ap.add_argument("--since", type=date.fromisoformat, default=date(1999, 1, 1))
    ap.add_argument("--rate", type=float, default=5.0, help="max requests per second")
    ap.add_argument("--workers", type=int, default=4, help="parallel image downloads")
    ap.add_argument("--dry-run", action="store_true", help="count the gaps, download nothing")
    ap.add_argument("--retry", action="store_true", help="retry cards pokemontcg.io didn't have last time")
    args = ap.parse_args(argv)

    data_dir: Path = args.data_dir
    catalog_path = data_dir / f"catalog_{LANG}.jsonl"
    misses_path = data_dir / "cache" / f"image_gaps_{LANG}.json"
    ptcg_sets_path = data_dir / "cache" / "ptcg_sets.json"
    limiter = RateLimiter(args.rate)
    client = TcgdexClient(LANG)

    set_info = load_set_dates(client, data_dir / "cache" / f"sets_{LANG}.json", limiter)
    set_ids = select_sets(set_info, args.since)
    if not ptcg_sets_path.exists():
        from server.pricing.pokemontcg import PokemonTcgClient

        ptcg_sets_path.write_text(json.dumps(PokemonTcgClient().sets()))
    set_map = build_set_map({k: set_info[k] for k in set_ids}, json.loads(ptcg_sets_path.read_text()))
    misses: dict[str, str] = json.loads(misses_path.read_text()) if misses_path.exists() else {}

    done = load_done(catalog_path, ROOT)
    skip = done | (set() if args.retry else set(misses))
    print(f"{len(set_ids)} TCGdex sets, {len(set_map)} mapped to pokemontcg.io; looking for cards without image…")
    gaps = find_gaps(client, set_ids, skip, limiter)
    print(f"{len(gaps)} cards without image to try" + ("" if args.retry else f" ({len(misses)} known misses skipped)"))
    if args.dry_run:
        by_set = Counter(set_id for set_id, _, _ in gaps)
        for set_id, n in by_set.most_common():
            print(f"  {set_id:12s} {n:4d}  -> {set_map.get(set_id, '(no pokemontcg.io set)')}")
        return 0

    counts = fill(gaps, set_map, data_dir, catalog_path, misses, limiter, workers=args.workers)
    misses_path.parent.mkdir(parents=True, exist_ok=True)
    misses_path.write_text(json.dumps(misses, indent=1, sort_keys=True))
    print(f"filled {counts['filled']}, not on pokemontcg.io {counts['not_found']}, "
          f"set not on pokemontcg.io {counts['no_mapping']}")
    for key, n in sorted(counts.items()):
        if key.startswith("filled:"):
            print(f"  {key[7:]:12s} +{n}")
    print("next: python scripts/build_index.py --model dinov2 --append")
    return 0


if __name__ == "__main__":
    sys.exit(main())
