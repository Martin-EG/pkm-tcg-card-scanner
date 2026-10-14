"""Identification pipeline and HTTP API on a tiny fake catalog (no model downloads)."""

import json

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

import server.recognition.identify as identify_module
from server.recognition import index as faiss_index
from server.api.app import create_app
from server.storage.db import Store
from server.config.settings import Settings
from server.recognition.embedders import embed_cards
from tests.recognition.test_crop import binder_page, colored_card


class FakeEmbedder:
    """Unit vector from the image's mean colour plus a coarse 3x3 colour layout."""

    name, dim = "fake", 30

    def embed(self, images):
        out = []
        for im in images:
            a = np.asarray(im.convert("RGB").resize((3, 3), Image.BILINEAR), dtype=np.float32).ravel() / 255
            v = np.concatenate([a, np.asarray(im, dtype=np.float32).mean(axis=(0, 1)) / 255])
            out.append(v / (np.linalg.norm(v) + 1e-9))
        return np.array(out, dtype=np.float32)


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    """Catalogs for en and es: cards 0-8 drawn by colored_card; es has the same art."""
    monkeypatch.setattr(identify_module, "load_embedder", lambda name: FakeEmbedder())
    monkeypatch.setitem(identify_module._ID, "min_score", 0.5)
    data = tmp_path / "data"
    emb = FakeEmbedder()
    for lang in ("en", "es"):
        rows, cards = [], []
        for i in range(9):
            rows.append({"id": f"t1-{i + 1:03d}", "name": f"Card {i}", "set": "t1", "set_name": "Test",
                         "number": f"{i + 1:03d}", "language": lang,
                         "image_path": f"data/images/{lang}/t1/t1-{i + 1:03d}.webp"})
            cards.append(Image.fromarray(cv2.cvtColor(colored_card(i), cv2.COLOR_BGR2RGB)))
        (data / "cache").mkdir(parents=True, exist_ok=True)
        (data / f"catalog_{lang}.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
        (data / "cache" / f"sets_{lang}.json").write_text(json.dumps(
            {"t1": {"abbreviation": "TST", "official_count": 9}}))
        vecs = embed_cards(emb, cards)
        faiss_index.save(faiss_index.build(vecs), [r["id"] for r in rows], data / "index", "dinov2", lang)
    return data


def test_only_enabled_languages_are_returned(data_dir):
    crops = [colored_card(i) for i in range(3)]
    en_only = identify_module.Identifier(("en",), data_dir, ocr=False).identify_cards(crops)
    assert all(c.lang == "en" for r in en_only for c in r.candidates)
    assert [r.candidates[0].card_id for r in en_only] == ["t1-001", "t1-002", "t1-003"]
    both = identify_module.Identifier(("en", "es"), data_dir, ocr=False).identify_cards(crops)
    assert {c.lang for r in both for c in r.candidates} == {"en", "es"}


def test_card_in_language_without_catalog_is_flagged(data_dir):
    from server.recognition.ocr import CardText

    class Reader:
        def __init__(self, languages):
            self.languages = languages

        def read(self, card, codes, prefixes):
            return CardText(languages=self.languages)

    ident = identify_module.Identifier(("en",), data_dir, ocr=False)
    ident.reader = Reader({"es"})
    r = ident.identify_cards([colored_card(0)])[0]
    assert r.foreign_language == "es"
    assert r.candidates[0].card_id == "t1-001" and r.candidates[0].lang == "en"  # same art, English match
    ident.reader = Reader({"en"})
    assert ident.identify_cards([colored_card(0)])[0].foreign_language is None


def test_enabled_language_without_index_is_skipped(data_dir):
    for f in (data_dir / "index").glob("dinov2_es*"):
        f.unlink()
    ident = identify_module.Identifier(("en", "es"), data_dir, ocr=False)
    assert ident.languages == ("en",)


def test_more_than_one_language_always_asks_for_ocr(data_dir):
    ident = identify_module.Identifier(("en", "es"), data_dir, ocr=False)
    ranked = [(("en", "t1-001"), (0.99, 0)), (("es", "t1-005"), (0.50, 0))]
    assert ident._ambiguous(ranked)


def test_same_name_in_top_k_asks_for_ocr(data_dir, monkeypatch):
    monkeypatch.setitem(identify_module._OCR, "read_every_card", False)
    ident = identify_module.Identifier(("en",), data_dir, ocr=False)
    ident.catalogs["en"].rows["t1-002"]["name"] = "Card 0"  # a reprint of card 0
    ranked = [(("en", "t1-001"), (0.99, 0)), (("en", "t1-002"), (0.80, 0)), (("en", "t1-003"), (0.7, 0))]
    assert ident._ambiguous(ranked)
    ranked[1] = (("en", "t1-004"), (0.80, 0))
    assert not ident._ambiguous(ranked)


@pytest.fixture
def client(data_dir, tmp_path):
    ident = identify_module.Identifier(("en",), data_dir, ocr=False)
    store = Store(tmp_path / "server.storage.db")
    app = create_app(identifier=ident, store=store, scans_dir=tmp_path / "scans",
                     sessions=object(), settings=Settings())  # pricing is covered in test_sessions_api
    with TestClient(app) as c:
        c.store = store
        yield c


def _jpeg(img):
    return cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 95])[1].tobytes()


def test_identify_binder_page(client):
    r = client.post("/identify", files={"photo": ("page.jpg", _jpeg(binder_page()), "image/jpeg")})
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["cards"]) == 9
    assert [c["candidates"][0]["id"] for c in body["cards"]] == [f"t1-{i:03d}" for i in range(1, 10)]
    first = body["cards"][0]
    assert first["language"] == "en" and len(first["candidates"]) == 3
    assert all(0 <= c["confidence"] <= 1 for card in body["cards"] for c in card["candidates"])
    assert client.get(first["crop_url"]).status_code == 200
    row = client.store.get_card(body["scan_id"], 0)
    assert row["top_card_id"] == "t1-001"


def test_blurry_photo_is_a_clear_error(client):
    photo = cv2.GaussianBlur(binder_page(), (0, 0), 12)
    r = client.post("/identify", files={"photo": ("page.jpg", _jpeg(photo), "image/jpeg")})
    assert r.status_code == 422
    assert r.json()["error"] == "blurry"


def test_photo_with_no_card_is_a_clear_error(client):
    noise = np.random.default_rng(3).integers(0, 255, (900, 700, 3), dtype=np.uint8)
    r = client.post("/identify", files={"photo": ("x.jpg", _jpeg(noise), "image/jpeg")})
    assert r.status_code == 422
    assert r.json()["error"] == "no_card"


def test_not_an_image(client):
    r = client.post("/identify", files={"photo": ("x.jpg", b"not a photo", "image/jpeg")})
    assert r.status_code == 422 and r.json()["error"] == "bad_image"


def test_correction_is_stored(client):
    scan = client.post("/identify", files={"photo": ("p.jpg", _jpeg(binder_page()), "image/jpeg")}).json()
    r = client.post("/corrections", json={"scan_id": scan["scan_id"], "card_index": 0, "card_id": "t1-005"})
    assert r.status_code == 200
    row = client.store.conn.execute("SELECT * FROM corrections").fetchone()
    assert (row["card_id"], row["proposed_card_id"], row["language"]) == ("t1-005", "t1-001", "en")


def test_correction_rejects_unknown_scan_or_card(client):
    assert client.post("/corrections", json={"scan_id": 999, "card_index": 0, "card_id": "t1-001"}).status_code == 404
    scan = client.post("/identify", files={"photo": ("p.jpg", _jpeg(binder_page()), "image/jpeg")}).json()
    r = client.post("/corrections", json={"scan_id": scan["scan_id"], "card_index": 0, "card_id": "nope"})
    assert r.status_code == 422


def test_image_route_blocks_path_traversal(client):
    assert client.get("/images/../../etc/passwd").status_code == 404
