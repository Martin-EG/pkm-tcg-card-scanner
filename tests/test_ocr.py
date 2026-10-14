"""Parsing of recorded OCR output from real counter photos (Phase 0 crops)."""

import pytest

from scanner.ocr import (CardMeta, CardText, lookup_by_text, name_bar_languages, normalize_number,
                         parse_card_text, text_bonus)

CODES = {"MEW", "PAF", "MEE", "PRE", "SVI", "SVP", "DRI", "CRI", "30C"}


@pytest.mark.parametrize("raw,want", [("004", "4"), ("O10", "10"), ("swsh164", "SWSH164"), ("TG01", "TG1"), ("173", "173")])
def test_normalize_number(raw, want):
    assert normalize_number(raw) == want


@pytest.mark.parametrize(
    "texts,number,total,code,lang",
    [
        (["illus. GIDORA", "MEW EN", "tail.it", "004/165"], "4", 165, "MEW", "en"),
        (["PAFEN", "To st", "057/091", "5"], "57", 91, "PAF", "en"),
        (["G PAF EN", "057/091"], "57", 91, "PAF", "en"),
        (["e", "PREEN", "022/131"], "22", 131, "PRE", "en"),
        (["SYIEJ203/198", "©2023 Pokemon / Nintendo"], "203", 198, "SVI", None),
        (["DRIEN", "190/182", "*"], "190", 182, "DRI", "en"),
        (["m3:0303", "JCRIEM", "025/086"], "25", 86, "CRI", "en"),
    ],
)
def test_parse_modern_cards(texts, number, total, code, lang):
    t = parse_card_text(texts, CODES)
    assert number in t.numbers
    assert total in t.totals
    assert code in t.set_codes
    if lang:
        assert lang in t.languages


def test_promo_number_without_total():
    t = parse_card_text(["SVP EN 173", "ex"], CODES)
    assert t.numbers == {"173"} and t.set_codes == {"SVP"} and "en" in t.languages
    t = parse_card_text(["HSVPEN173"], CODES)
    assert "173" in t.numbers and "SVP" in t.set_codes


def test_energy_with_look_alike_digits():
    t = parse_card_text(["MEEN", "O10 IllUs. YOSHIROTTEN"], CODES)
    assert "MEE" in t.set_codes and "10" in t.numbers


def test_spanish_artist_credit_sets_language():
    t = parse_card_text(["Ilus. GIDORA", "MEW", "004/165"], CODES)
    assert "es" in t.languages
    t = parse_card_text(["MEW ES", "004/165"], CODES)
    assert "es" in t.languages


def test_japanese_text_sets_language():
    assert "ja" in parse_card_text(["ヒトカゲ", "004/165"], CODES).languages


def test_ordinary_words_are_not_set_codes():
    t = parse_card_text(["From the time it is born, a flame burns"], CODES)
    assert not t.set_codes
    t = parse_card_text(["Mega Evolutio", "ex rule"], CODES | {"MEG"})
    assert not t.set_codes


def test_code_garbled_by_rarity_stars():
    t = parse_card_text(["lus. Sbon Graphics", "CRLENAPOPE"], CODES)
    assert "CRI" in t.set_codes and "en" in t.languages


@pytest.mark.parametrize("texts,code", [(["JTGIA", "SUR", "163/159"], "JTG"), (["JTG LA", "163/159"], "JTG"),
                                        (["I SVPA189 ", "men"], "SVP")])
def test_latin_american_spanish_tag(texts, code):
    t = parse_card_text(texts, CODES | {"JTG"})
    assert code in t.set_codes and t.languages == {"es"}


def _meta(cid, number, code, count, lang="en", name="Charmander"):
    return CardMeta(cid, lang, name, cid.split("-")[0], normalize_number(number), code, count)


def test_bonus_breaks_same_art_reprint_tie():
    t = parse_card_text(["MEW EN", "004/165"], CODES)
    mew = _meta("sv03.5-004", "004", "MEW", 165)
    paf = _meta("sv04.5-007", "007", "PAF", 91)
    assert text_bonus(mew, t) > text_bonus(paf, t) + 0.1


def test_lookup_by_code_and_number():
    metas = [_meta("sv03.5-004", "004", "MEW", 165), _meta("sv04.5-007", "007", "PAF", 91),
             _meta("sv03.5-004", "004", "MEW", 165, lang="es")]
    t = parse_card_text(["MEW EN", "004/165"], CODES)
    assert [(m.card_id, m.lang) for m in lookup_by_text(t, metas)] == [("sv03.5-004", "en")]


def test_lookup_old_cards_by_number_and_set_size():
    metas = [_meta("base1-4", "4", None, 102, name="Charizard"), _meta("base2-4", "4", None, 64)]
    t = parse_card_text(["4/102"], set())
    assert [m.card_id for m in lookup_by_text(t, metas)] == ["base1-4"]


def test_lookup_needs_a_number():
    assert lookup_by_text(CardText(set_codes={"MEW"}), [_meta("sv03.5-004", "004", "MEW", 165)]) == []


@pytest.mark.parametrize("texts,lang", [
    (["1300", "Noゼクロム", "HP"], "ja"),
    (["BASICO", "ZoruadeN"], "es"),
    (["Zoruade N", "700"], "es"),
    (["FASE 1", "Kilowattrel"], "es"),
    (["STAGET", "Armarouge", "5"], "en"),
    (["BASIC", "Pikachu", "HP 60"], "en"),
])
def test_name_bar_language(texts, lang):
    assert lang in name_bar_languages(texts)


def test_plain_english_name_has_no_spanish_hit():
    assert "es" not in name_bar_languages(["Iono's Bellibolt ex", "HP280"])


def test_one_stray_kana_is_not_japanese():
    assert "ja" not in name_bar_languages(["STAGE1", "Armarougeク"])
