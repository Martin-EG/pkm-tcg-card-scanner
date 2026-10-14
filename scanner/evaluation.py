"""Helpers for scoring identification results against labeled photos."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".bmp"}
# Extra photos of the same card: sv06-123_2.jpg, sv06-123 (2).jpg
_COPY_SUFFIX = re.compile(r"(_\d+|\s*\(\d+\))$")


def card_id_from_filename(path: Path | str) -> str:
    """'sv06-123_2.JPG' -> 'sv06-123'. Case of the id is kept as-is."""
    stem = Path(path).stem.strip()
    return _COPY_SUFFIX.sub("", stem)


def list_photos(folder: Path) -> list[Path]:
    return sorted(p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTS)


@dataclass
class Result:
    photo: str
    true_id: str
    predictions: list[tuple[str, float]]
    seconds: float
    cropped: bool

    def rank(self) -> int | None:
        """1-based rank of the true id, or None if not in the predictions."""
        for i, (cid, _) in enumerate(self.predictions, start=1):
            if cid.lower() == self.true_id.lower():
                return i
        return None


@dataclass
class Summary:
    model: str
    n: int
    top1: float
    top3: float
    mean_seconds: float
    max_seconds: float
    crop_rate: float
    failures: list[Result] = field(default_factory=list)


def summarize(model: str, results: list[Result]) -> Summary:
    n = len(results)
    if n == 0:
        return Summary(model, 0, 0.0, 0.0, 0.0, 0.0, 0.0, [])
    ranks = [r.rank() for r in results]
    top1 = sum(1 for k in ranks if k == 1) / n
    top3 = sum(1 for k in ranks if k is not None and k <= 3) / n
    secs = [r.seconds for r in results]
    return Summary(
        model=model,
        n=n,
        top1=top1,
        top3=top3,
        mean_seconds=sum(secs) / n,
        max_seconds=max(secs),
        crop_rate=sum(r.cropped for r in results) / n,
        failures=[r for r, k in zip(results, ranks) if k != 1],
    )
