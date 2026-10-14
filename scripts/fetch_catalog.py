"""Download a TCGdex catalog (English, Spanish, or Japanese) with high-resolution card images.

Usage:
    python scripts/fetch_catalog.py                 # English sets released in the last 3 years
    python scripts/fetch_catalog.py --since 1999-01-01
    python scripts/fetch_catalog.py --lang es --since 1999-01-01
    python scripts/fetch_catalog.py --sets sv06 svp # explicit sets, ignores dates

Writes data/catalog_<lang>.jsonl (one card per line) and data/images/<lang>/<set>/<card>.webp,
plus data/cache/sets_<lang>.json with each set's date, printed code, and printed size.
Safe to interrupt: re-running skips cards whose row and image already exist.

Talks to the TCGdex REST API directly: the Python SDK fails to parse some Spanish
and Japanese sets and doesn't expose the printed set code.
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

LANGUAGES = ("en", "es", "ja")
# TCG Pocket is a mobile game; its cards are never physical.
EXCLUDED_SERIES = {"tcgp"}
ROOT = Path(__file__).resolve().parent.parent
API = "https://api.tcgdex.net/v2"
USER_AGENT = "tcg-buylist-scanner/0.1 (catalog fetch)"


class TcgdexClient:
    """Minimal TCGdex REST client for one language."""

    def __init__(self, lang: str, timeout: float = 30.0):
        self.lang = lang
        self.timeout = timeout

    def _get(self, url: str) -> bytes:
        with urlopen(Request(url, headers={"User-Agent": USER_AGENT}), timeout=self.timeout) as r:
            return r.read()

    def list_sets(self) -> list[dict]:
        return json.loads(self._get(f"{API}/{self.lang}/sets"))

    def get_set(self, set_id: str) -> dict:
        return json.loads(self._get(f"{API}/{self.lang}/sets/{quote(set_id)}"))

    def get_image(self, card: dict) -> bytes:
        return self._get(f"{card['image']}/high.webp")


class RateLimiter:
    """At most `per_second` calls per second across the whole run."""

    def __init__(self, per_second: float):
        self.interval = 1.0 / per_second if per_second > 0 else 0.0
        self.next_slot = 0.0
        self.lock = threading.Lock()

    def wait(self) -> None:
        # Reserve the next free slot under the lock, then sleep outside it.
        with self.lock:
            now = time.monotonic()
            slot = max(now, self.next_slot)
            self.next_slot = slot + self.interval
        if slot > now:
            time.sleep(slot - now)


def with_retries(fn, limiter: RateLimiter, attempts: int = 5):
    """Call fn() under the rate limit; back off on 429, 5xx, and network errors."""
    for attempt in range(attempts):
        limiter.wait()
        try:
            return fn()
        except HTTPError as e:
            if e.code == 404:
                raise
            if e.code != 429 and e.code < 500:
                raise
            retry_after = e.headers.get("Retry-After") if e.headers else None
            delay = float(retry_after) if retry_after and retry_after.isdigit() else 2 ** (attempt + 1)
        except (URLError, TimeoutError, ConnectionError) as e:
            delay = 2 ** (attempt + 1)
            if attempt == attempts - 1:
                raise
            print(f"  network error ({e}); retrying in {delay}s", file=sys.stderr)
        if attempt == attempts - 1:
            raise RuntimeError("too many retries")
        time.sleep(delay)


def load_done(catalog_path: Path, root: Path) -> set[str]:
    """Card ids already in the catalog whose image file exists."""
    done: set[str] = set()
    if not catalog_path.exists():
        return done
    for line in catalog_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue  # a line cut off by an interrupted run
        if (root / row["image_path"]).exists():
            done.add(row["id"])
    return done


def compact_catalog(catalog_path: Path, root: Path) -> int:
    """Drop broken, duplicate, or image-less rows (left by interrupted runs)."""
    if not catalog_path.exists():
        return 0
    rows: dict[str, dict] = {}
    for line in catalog_path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if (root / row["image_path"]).exists():
            rows[row["id"]] = row
    tmp = catalog_path.with_suffix(".tmp")
    tmp.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows.values()), encoding="utf-8")
    tmp.replace(catalog_path)
    return len(rows)


# Keys every cached set entry must have; older cache entries missing one are fetched again.
SET_KEYS = ("releaseDate", "serie", "name", "abbreviation", "official_count")


def load_set_dates(client: TcgdexClient, cache_path: Path, limiter: RateLimiter) -> dict[str, dict]:
    """{set_id: {releaseDate, serie, name, abbreviation, official_count}} for every set in
    the client's language; cached on disk. abbreviation is the printed set code (e.g. "MEE")
    and official_count the printed set size (the 131 of 022/131); both feed the OCR step."""
    cache: dict[str, dict] = json.loads(cache_path.read_text()) if cache_path.exists() else {}
    listed = with_retries(client.list_sets, limiter)
    missing = [s["id"] for s in listed if not all(k in cache.get(s["id"], {}) for k in SET_KEYS)]
    for i, set_id in enumerate(missing, 1):
        print(f"  set info {i}/{len(missing)}: {set_id}")
        s = with_retries(lambda: client.get_set(set_id), limiter)
        cache[set_id] = {
            "releaseDate": s.get("releaseDate"),
            "serie": (s.get("serie") or {}).get("id"),
            "name": s.get("name"),
            "abbreviation": (s.get("abbreviation") or {}).get("official"),
            "official_count": (s.get("cardCount") or {}).get("official"),
        }
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(cache, indent=1))
    return cache


def select_sets(set_info: dict[str, dict], since: date) -> list[str]:
    chosen = [
        sid
        for sid, info in set_info.items()
        if info["serie"] not in EXCLUDED_SERIES and info["releaseDate"] and info["releaseDate"] >= since.isoformat()
    ]
    return sorted(chosen, key=lambda sid: (set_info[sid]["releaseDate"], sid))


def download_card_image(client: TcgdexClient, card: dict, dest: Path, limiter: RateLimiter) -> bool:
    if not card.get("image"):
        return False
    data = with_retries(lambda: client.get_image(card), limiter)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".part")
    tmp.write_bytes(data)
    tmp.replace(dest)  # atomic: a half-written file never looks finished
    return True


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--lang", choices=LANGUAGES, default="en")
    ap.add_argument("--since", type=date.fromisoformat, default=date.today() - timedelta(days=3 * 365))
    ap.add_argument("--sets", nargs="*", help="explicit set ids (skips the date filter)")
    ap.add_argument("--data-dir", type=Path, default=ROOT / "data")
    ap.add_argument("--rate", type=float, default=5.0, help="max requests per second")
    ap.add_argument("--workers", type=int, default=4, help="parallel image downloads")
    args = ap.parse_args(argv)

    data_dir: Path = args.data_dir
    data_dir.mkdir(parents=True, exist_ok=True)
    lang = args.lang
    catalog_path = data_dir / f"catalog_{lang}.jsonl"
    client = TcgdexClient(lang)
    limiter = RateLimiter(args.rate)

    kept = compact_catalog(catalog_path, ROOT)
    done = load_done(catalog_path, ROOT)
    print(f"catalog: {kept} cards already downloaded")

    if args.sets:
        set_ids = args.sets
    else:
        set_info = load_set_dates(client, data_dir / "cache" / f"sets_{lang}.json", limiter)
        set_ids = select_sets(set_info, args.since)
        print(f"{len(set_ids)} sets released since {args.since}: {' '.join(set_ids)}")

    added = no_image = 0
    with catalog_path.open("a", encoding="utf-8") as out:
        for set_id in set_ids:
            s = with_retries(lambda: client.get_set(set_id), limiter)
            cards = s.get("cards", [])
            todo = [c for c in cards if c["id"] not in done]
            print(f"{set_id} ({s['name']}): {len(cards)} cards, {len(todo)} to download")

            def fetch(card):
                dest = (data_dir / "images" / lang / set_id / f"{card['id']}.webp").resolve()
                try:
                    return card, dest, download_card_image(client, card, dest, limiter)
                except HTTPError as e:
                    if e.code != 404:
                        raise
                    return card, dest, False

            with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
                # Rows are written from this thread only, as each download finishes.
                for card, dest, ok in pool.map(fetch, todo):
                    if not ok:
                        no_image += 1
                        print(f"  {card['id']}: no image on TCGdex, skipped")
                        continue
                    row = {
                        "id": card["id"],
                        "name": card["name"],
                        "set": set_id,
                        "set_name": s["name"],
                        "number": card["localId"],
                        "language": lang,
                        "image_path": str(dest.relative_to(ROOT)) if dest.is_relative_to(ROOT) else str(dest),
                    }
                    out.write(json.dumps(row, ensure_ascii=False) + "\n")
                    out.flush()
                    done.add(card["id"])
                    added += 1

    total = compact_catalog(catalog_path, ROOT)
    print(f"done: {added} new cards, {no_image} without image, {total} in {catalog_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
