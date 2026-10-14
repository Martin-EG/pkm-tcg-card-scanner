"""Read the card's bottom strip (set code, language tag, collector number) and use it
to re-rank the visual candidates.

Modern cards print e.g. "PRE EN 022/131" bottom left; OCR often merges the parts
("PREEN", "G PAF EN057/091") and confuses look-alike characters ("O10", "SYIEJ").
Older cards print only "22/102" bottom right. Parsing is kept separate from the
OCR engine so it can be tested on recorded OCR output.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

import numpy as np

from server.config.rules import rules

_CFG = rules()["ocr"]

NUMBER_TOTAL = re.compile(r"([0-9OIl]{1,3})\s*/\s*([0-9OIl]{2,3})")
# Promo-style numbers printed as one token: SWSH164, XY116, SM110, TG01, GG05, SV001.
PROMO_NUMBER = re.compile(r"\b([A-Z]{2,5})(\d{1,3})\b")
# A token that is only a number, allowing look-alike letters but at least one digit.
LONE_NUMBER = re.compile(r"^(?=.*\d)[0-9OIl]{2,3}$")
# What may follow a set code inside one OCR token: language tag, then the number,
# possibly garbled by the rarity symbols printed right after it ("CRLENAPOPE").
_CODE_REST = re.compile(r"^[A-Za-z0-9]{0,8}$")
# Look-alikes OCR swaps inside numbers.
_DIGIT_FIX = str.maketrans({"O": "0", "o": "0", "I": "1", "l": "1"})
# Look-alikes OCR swaps inside set codes (compared after mapping both sides).
_CODE_FIX = str.maketrans({"Y": "V", "0": "O", "1": "I", "L": "I", "5": "S"})
# Printed language tags after the set code, as OCR tends to read them. Cards sold in
# Mexico are Latin American Spanish prints, tagged "LA" (often read "IA").
_LANG_TAGS = {"en": ("EN", "EH", "EM", "EI"), "es": ("ES", "LA", "IA", "1A")}
_JAPANESE = re.compile(r"[぀-ヿ一-鿿]")
_KANA = re.compile(r"[\u3040-\u30ff]")
# Words printed in the name bar: the stage ("BASIC" / "BÁSICO", "STAGE 1" / "FASE 1")
# and Spanish name patterns ("Zorua de N").
_NAME_WORDS = {
    "en": re.compile(r"\b(BASIC|STAGE\s?[12I]?|STAGET)\b", re.IGNORECASE),
    "es": re.compile(r"(B[AÁ]SICO|\bFASE\s?[12I]?\b|[a-z]de\s?[A-Z]\b|\bde\s[A-Z])"),
}


def name_bar_languages(texts: list[str]) -> set[str]:
    """Languages suggested by the name bar's text."""
    joined = " ".join(texts)
    found = {lang for lang, pattern in _NAME_WORDS.items() if pattern.search(joined)}
    if len(_KANA.findall(joined)) >= _CFG["min_kana"]:
        found.add("ja")
    return found


def normalize_number(number: str) -> str:
    """'004' -> '4', 'O10' -> '10', 'swsh164' -> 'SWSH164', 'TG01' -> 'TG1'."""
    number = number.strip().upper()
    fixed = number.translate(_DIGIT_FIX)
    if fixed.isdigit():
        return str(int(fixed))
    m = re.fullmatch(r"([A-Z]+)0*(\d+)", number)
    return f"{m.group(1)}{m.group(2)}" if m else number


@dataclass
class CardText:
    numbers: set[str] = field(default_factory=set)
    totals: set[int] = field(default_factory=set)
    set_codes: set[str] = field(default_factory=set)
    languages: set[str] = field(default_factory=set)
    raw: list[str] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return not (self.numbers or self.set_codes)


def _match_code(token: str, known_codes: set[str]) -> tuple[str, str] | None:
    """(code, rest of token) for the longest known code at the start of the token,
    allowing one leading regulation-mark letter ("GPAF", "JCRIEm"). Codes are printed
    in capitals, so a match must be read in capitals ("Mega" is not the code MEG)."""
    best = None
    upper = token.upper().translate(_CODE_FIX)
    for start in (0, 1):
        rest = upper[start:]
        for code in known_codes:
            fixed = code.upper().translate(_CODE_FIX)
            # The remainder is checked on the original token: _CODE_FIX turns digits into letters.
            read = token[start:start + len(code)]
            if (rest.startswith(fixed) and read == read.upper() and _CODE_REST.match(token[start + len(code):])
                    and (best is None or len(code) > len(best[0]))):
                best = (code, token[start + len(code):])
    return best


def _language_from_tag(rest: str) -> str | None:
    # "SVPA189": OCR dropped the L of "LA" right before the number.
    if re.match(r"^A\d", rest):
        return "es"
    tag = rest[:2].upper()
    for lang, tags in _LANG_TAGS.items():
        if tag in tags:
            return lang
    return None


def parse_card_text(texts: list[str], known_codes: set[str], promo_prefixes: set[str] = frozenset()) -> CardText:
    out = CardText(raw=list(texts))
    lone: set[str] = set()
    min_len = _CFG["min_code_length"]
    codes = {c for c in known_codes if c and len(c) >= min_len}
    joined = " ".join(texts)
    for text in texts:
        for number, total in NUMBER_TOTAL.findall(text):
            out.numbers.add(normalize_number(number))
            out.totals.add(int(total.translate(_DIGIT_FIX)))
        for prefix, digits in PROMO_NUMBER.findall(text.upper()):
            if prefix in promo_prefixes:
                out.numbers.add(normalize_number(prefix + digits))
        for token in re.split(r"[^A-Za-z0-9]+", text):
            hit = _match_code(token, codes) if token else None
            if not hit:
                continue
            code, rest = hit
            out.set_codes.add(code)
            lang = _language_from_tag(rest) or (_language_from_tag(_next_word(text, token)) if not rest else None)
            if lang:
                out.languages.add(lang)
            # "HSVPEN173": the number can follow the code and tag in the same token.
            tail = re.search(r"(\d{1,3})$", rest)
            if tail and not out.numbers:
                lone.add(normalize_number(tail.group(1)))
        for token in text.split():
            if LONE_NUMBER.match(token):
                lone.add(normalize_number(token))
    # Promo cards print only '173' next to the set code; use lone numbers only then.
    if not out.numbers and out.set_codes:
        out.numbers |= lone
    # Spanish cards credit the artist as "Ilus." and English ones as "Illus.".
    if re.search(r"\bIlus\b", joined) and not re.search(r"\bIllus\b", joined, re.IGNORECASE):
        out.languages.add("es")
    if _JAPANESE.search(joined):
        out.languages.add("ja")
    return out


def _next_word(text: str, token: str) -> str:
    after = text.split(token, 1)[1] if token in text else ""
    words = after.split()
    return words[0] if words else ""


@dataclass(frozen=True)
class CardMeta:
    card_id: str
    lang: str
    name: str
    set_id: str
    number: str  # normalized
    set_code: str | None
    set_official_count: int | None


def text_bonus(meta: CardMeta, text: CardText) -> float:
    w = _CFG["weights"]
    bonus = 0.0
    if meta.number in text.numbers:
        bonus += w["number"]
        if meta.set_official_count in text.totals:
            bonus += w["total"]
    if meta.set_code and meta.set_code in text.set_codes:
        bonus += w["set_code"]
    if meta.lang in text.languages:
        bonus += w["language"]
    return bonus


def lookup_by_text(text: CardText, metas: list[CardMeta]) -> list[CardMeta]:
    """Cards whose printed identity matches the text exactly: (set code, number) when a
    code was read, otherwise (number, set size) for older cards that print no code."""
    if not text.numbers:
        return []
    hits = []
    for m in metas:
        if m.number not in text.numbers:
            continue
        if text.set_codes:
            if m.set_code in text.set_codes:
                hits.append(m)
        elif m.set_official_count in text.totals:
            hits.append(m)
    if text.languages:
        hits = [m for m in hits if m.lang in text.languages] or hits
    return hits if len(hits) <= _CFG["max_lookup_results"] else []


class CardTextReader:
    """PaddleOCR on the name bar and bottom strip of a cropped, upright card. Loads lazily."""

    def __init__(self):
        self._engines: dict[str, object] = {}

    def _engine(self, model_key: str = "recognition_model"):
        if model_key not in self._engines:
            os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
            from paddleocr import PaddleOCR

            self._engines[model_key] = PaddleOCR(
                text_detection_model_name=_CFG["detection_model"],
                text_recognition_model_name=_CFG[model_key],
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                use_textline_orientation=False,
            )
        return self._engines[model_key]

    def read_region(self, card_bgr: np.ndarray, region: int) -> list[str]:
        h, w = card_bgr.shape[:2]
        x0, x1 = _CFG["regions"][region]
        strip = card_bgr[int(h * _CFG["strip_top"]):int(h * _CFG["strip_bottom"]), int(w * x0):int(w * x1)]
        result = self._engine().predict(np.ascontiguousarray(strip))
        return list(result[0]["rec_texts"]) if result else []

    def read_name_bar(self, card_bgr: np.ndarray) -> list[str]:
        h = card_bgr.shape[0]
        top, bottom = _CFG["name_strip"]
        strip = np.ascontiguousarray(card_bgr[int(h * top):int(h * bottom)])
        result = self._engine("name_recognition_model").predict(strip)
        return list(result[0]["rec_texts"]) if result else []

    def read(self, card_bgr: np.ndarray, known_codes: set[str], promo_prefixes: set[str]) -> CardText:
        texts: list[str] = []
        parsed = CardText()
        for region in range(len(_CFG["regions"])):
            texts += self.read_region(card_bgr, region)
            parsed = parse_card_text(texts, known_codes, promo_prefixes)
            if parsed.numbers:
                break
        name = self.read_name_bar(card_bgr)
        name_langs = name_bar_languages(name)
        # The printed tag ("EN", "LA") is the stronger signal; the name bar fills in
        # when no tag was read, and Japanese script always counts.
        if not parsed.languages or "ja" in name_langs:
            parsed.languages |= name_langs
        parsed.raw = name + parsed.raw
        return parsed
