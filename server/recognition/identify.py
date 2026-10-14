"""Photo -> identified cards: crop, embed, search the enabled language indexes, and
re-rank ambiguous results with OCR of the collector number and set code."""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from server.recognition import index as faiss_index
from server.paths import DATA
from server.recognition.catalog import Catalog, load_catalog
from server.config.rules import rules
from server.recognition.crop import PhotoError, crop_cards
from server.recognition.embedders import embed_cards, load_embedder
from server.recognition.ocr import CardText, CardTextReader, lookup_by_text, text_bonus

_ID = rules()["identification"]
_OCR = rules()["ocr"]


@dataclass
class Candidate:
    card_id: str
    lang: str
    name: str
    set_id: str
    set_name: str
    number: str
    score: float  # visual similarity plus any OCR bonus
    visual_score: float
    image_path: str


@dataclass
class CardResult:
    crop: np.ndarray  # upright card, BGR
    candidates: list[Candidate]
    confident: bool  # top visual score reached min_score
    ocr_used: bool
    text: CardText | None = None
    # Language read on the card when it has no catalog enabled ("es", "ja"): the
    # candidates are the same artwork in English, and the employee must check.
    foreign_language: str | None = None
    # Low similarity or a flagged language: show the candidates, but ask the employee.
    needs_review: bool = False
    timings: dict[str, float] = field(default_factory=dict)

    @property
    def language(self) -> str | None:
        return self.candidates[0].lang if self.candidates else None


class Identifier:
    def __init__(self, languages: tuple[str, ...] = ("en",), data_dir: Path = DATA, ocr: bool = True):
        self.embedder = load_embedder(_ID["model"])
        self.indexes = {}
        self.catalogs: dict[str, Catalog] = {}
        for lang in languages:
            if lang != "en" and not faiss_index.index_paths(data_dir / "index", _ID["model"], lang)[0].exists():
                print(f"WARNING: {lang} is enabled but has no index; its cards will be flagged, not matched",
                      file=sys.stderr)
                continue
            self.indexes[lang] = faiss_index.load(data_dir / "index", _ID["model"], lang)
            self.catalogs[lang] = load_catalog(lang, data_dir)
        self.languages = tuple(self.indexes)
        self.reader = CardTextReader() if ocr else None
        self.set_codes = set().union(*(c.set_codes for c in self.catalogs.values()))
        self.promo_prefixes = set().union(*(c.promo_prefixes for c in self.catalogs.values()))
        self.all_metas = [m for c in self.catalogs.values() for m in c.metas.values()]

    def identify_photo(self, image_bgr: np.ndarray) -> list[CardResult]:
        """Every card in the photo. Raises PhotoError for blurry photos and photos
        with no card, including a single crop that matches nothing in the catalog."""
        crops = crop_cards(image_bgr)
        results = self.identify_cards(crops)
        if len(results) == 1 and not results[0].confident:
            raise PhotoError("no_card", "No se encontró ninguna carta en la foto.")
        return results

    def identify_cards(self, crops: list[np.ndarray]) -> list[CardResult]:
        t0 = time.perf_counter()
        views: list[Image.Image] = []
        for crop in crops:
            pil = Image.fromarray(cv2.cvtColor(crop, cv2.COLOR_BGR2RGB))
            views += [pil, pil.rotate(180)] if _ID["try_flipped"] else [pil]
        vectors = embed_cards(self.embedder, views)
        per_card = 2 if _ID["try_flipped"] else 1
        embed_s = (time.perf_counter() - t0) / max(1, len(crops))

        results = []
        for i, crop in enumerate(crops):
            t1 = time.perf_counter()
            best: dict[tuple[str, str], tuple[float, int]] = {}
            for v_idx in range(per_card):
                vec = vectors[i * per_card + v_idx]
                for lang, (index, ids) in self.indexes.items():
                    for cid, score in faiss_index.search(index, ids, vec, _ID["candidates"]):
                        key = (lang, cid)
                        if score > best.get(key, (-1.0, 0))[0]:
                            best[key] = (score, v_idx)
            ranked = sorted(best.items(), key=lambda kv: kv[1][0], reverse=True)
            top_score, top_view = ranked[0][1] if ranked else (0.0, 0)
            upright = crop if top_view == 0 else cv2.rotate(crop, cv2.ROTATE_180)
            visual = {key: s for key, (s, _) in ranked}
            search_s = time.perf_counter() - t1

            text = None
            scores = dict(visual)
            if self.reader and self._ambiguous(ranked):
                t2 = time.perf_counter()
                text = self.reader.read(upright, self.set_codes, self.promo_prefixes)
                for meta in lookup_by_text(text, self.all_metas):
                    key = (meta.lang, meta.card_id)
                    if key not in scores:  # text found a card the image search missed
                        scores[key] = min(visual.values()) if visual else 0.0
                        visual.setdefault(key, scores[key])
                for (lang, cid) in scores:
                    scores[(lang, cid)] += text_bonus(self.catalogs[lang].metas[cid], text)
                ocr_s = time.perf_counter() - t2
            else:
                ocr_s = 0.0

            foreign = None
            if text is not None:
                # Japanese script wins: a Japanese card can also carry Latin "BASIC"-like text.
                unmatched = text.languages - set(self.languages)
                if "ja" in unmatched:
                    foreign = "ja"
                elif unmatched and "en" not in text.languages:
                    foreign = sorted(unmatched)[0]
            top = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[: _ID["top_k"]]
            final_score = top[0][1] if top else 0.0
            candidates = [self._candidate(lang, cid, s, visual[(lang, cid)]) for (lang, cid), s in top]
            results.append(CardResult(
                crop=upright,
                candidates=candidates,
                confident=top_score >= _ID["min_score"],
                ocr_used=text is not None,
                text=text,
                foreign_language=foreign,
                needs_review=foreign is not None or final_score < _ID["review_score"],
                timings={"embed": embed_s, "search": search_s, "ocr": ocr_s},
            ))
        return results

    def _ambiguous(self, ranked: list[tuple[tuple[str, str], tuple[float, int]]]) -> bool:
        if _OCR["read_every_card"] or len(self.languages) > 1:
            return True  # artwork is shared across languages; only text tells them apart
        if len(ranked) < 2:
            return False
        (l1, c1), (s1, _) = ranked[0]
        if s1 - ranked[1][1][0] < _OCR["ambiguous_margin"]:
            return True
        name = self.catalogs[l1].rows[c1]["name"]
        return any(self.catalogs[l].rows[c]["name"] == name for (l, c), _ in ranked[1:_ID["top_k"]])

    def _candidate(self, lang: str, cid: str, score: float, visual_score: float) -> Candidate:
        row = self.catalogs[lang].rows[cid]
        return Candidate(cid, lang, row["name"], row["set"], row["set_name"], row["number"],
                         round(float(score), 4), round(float(visual_score), 4), row["image_path"])
