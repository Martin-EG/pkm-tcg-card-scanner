"""build_index.py --append adds only the cards missing from the index."""

import json

import numpy as np
from PIL import Image

import scripts.build_index as bi
from server.recognition import index as faiss_index


class FakeEmbedder:
    name, dim = "fake", 3

    def embed(self, images):
        v = np.array([np.asarray(im, dtype=np.float32).mean(axis=(0, 1)) + 1 for im in images])
        return (v / np.linalg.norm(v, axis=1, keepdims=True)).astype(np.float32)


def _catalog(tmp_path, cards):
    lines = []
    for cid, color in cards:
        path = tmp_path / f"{cid}.png"
        Image.new("RGB", (60, 84), color).save(path)
        lines.append(json.dumps({"id": cid, "image_path": str(path)}))
    (tmp_path / "catalog.jsonl").write_text("\n".join(lines) + "\n")


def test_append_adds_only_new_cards(tmp_path, monkeypatch):
    monkeypatch.setattr(bi, "load_embedder", lambda name: FakeEmbedder())
    args = ["--model", "dinov2", "--catalog", str(tmp_path / "catalog.jsonl"), "--index-dir", str(tmp_path / "idx")]
    _catalog(tmp_path, [("a-1", (200, 0, 0)), ("a-2", (0, 200, 0))])
    assert bi.main(args) == 0
    index, ids = faiss_index.load(tmp_path / "idx", "dinov2", "en")
    before = index.reconstruct_n(0, index.ntotal)

    _catalog(tmp_path, [("a-1", (200, 0, 0)), ("a-2", (0, 200, 0)), ("b-1", (0, 0, 200))])
    calls = []
    real = bi.embed_cards
    monkeypatch.setattr(bi, "embed_cards", lambda e, imgs: calls.append(len(imgs)) or real(e, imgs))
    assert bi.main(args + ["--append"]) == 0
    index, ids = faiss_index.load(tmp_path / "idx", "dinov2", "en")
    assert ids == ["a-1", "a-2", "b-1"] and index.ntotal == 3
    assert calls == [1]  # only the new card was embedded
    assert np.allclose(index.reconstruct_n(0, 2), before)  # existing vectors untouched

    calls.clear()
    assert bi.main(args + ["--append"]) == 0 and calls == []  # nothing new: nothing to do
