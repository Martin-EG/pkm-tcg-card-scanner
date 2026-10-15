"""Filling TCGdex image gaps from pokemontcg.io, without the network."""

import io
import json

import pytest
from PIL import Image

import scripts.fill_image_gaps as fg
from scripts.fetch_catalog import RateLimiter


@pytest.mark.parametrize("ptcg_set,number,want", [
    ("svp", "203", "svp/203_hires.png"), ("hsp", "HGSS21", "hsp/HGSS21_hires.png"),
    ("sm35", "004", "sm35/4_hires.png"), ("swsh9tg", "TG01", "swsh9tg/TG01_hires.png"),
])
def test_image_url(ptcg_set, number, want):
    assert fg.image_url(ptcg_set, number) == f"https://images.pokemontcg.io/{want}"


class FakeTcgdex:
    sets = {
        "svp": {"id": "svp", "name": "SVP Black Star Promos", "cards": [
            {"id": "svp-001", "localId": "001", "name": "Sprigatito", "image": "https://assets/svp/001"},
            {"id": "svp-203", "localId": "203", "name": "Team Rocket's Wobbuffet"},
            {"id": "svp-204", "localId": "204", "name": "Not On Pokemontcg"},
        ]},
        "mep": {"id": "mep", "name": "MEP Black Star Promos", "cards": [
            {"id": "mep-078", "localId": "078", "name": "Toxel"},
        ]},
    }

    def get_set(self, set_id):
        return self.sets[set_id]


def _png():
    buf = io.BytesIO()
    Image.new("RGBA", (734, 1024), (40, 120, 200, 255)).save(buf, "PNG")
    return buf.getvalue()


def test_find_gaps_lists_only_cards_without_image_not_yet_in_catalog():
    gaps = fg.find_gaps(FakeTcgdex(), ["svp", "mep"], done={"svp-204"}, limiter=RateLimiter(0))
    assert [card["id"] for _, _, card in gaps] == ["svp-203", "mep-078"]


def test_fill_downloads_what_pokemontcg_has_and_records_misses(tmp_path, monkeypatch):
    monkeypatch.setattr(fg, "ROOT", tmp_path)
    data = tmp_path / "data"
    catalog = data / "catalog_en.jsonl"
    data.mkdir()
    catalog.write_text("")
    gaps = fg.find_gaps(FakeTcgdex(), ["svp", "mep"], done=set(), limiter=RateLimiter(0))
    asked = []

    def download(url):
        asked.append(url)
        return _png() if url.endswith("/svp/203_hires.png") else None

    misses = {}
    counts = fg.fill(gaps, {"svp": "svp"}, data, catalog, misses, RateLimiter(0), download, workers=1)
    assert (counts["filled"], counts["not_found"], counts["no_mapping"]) == (1, 1, 1)
    assert misses == {"svp-204": "not_found", "mep-078": "no_mapping"}
    assert "https://images.pokemontcg.io/svp/203_hires.png" in asked
    assert not any("mep" in u for u in asked)  # no pokemontcg.io set: nothing to ask

    row = json.loads(catalog.read_text().strip())
    assert row == {"id": "svp-203", "name": "Team Rocket's Wobbuffet", "set": "svp",
                   "set_name": "SVP Black Star Promos", "number": "203", "language": "en",
                   "image_path": "data/images/en/svp/svp-203.webp", "image_source": "pokemontcg"}
    with Image.open(tmp_path / row["image_path"]) as im:
        assert im.size == fg.SIZE and im.format == "WEBP"
