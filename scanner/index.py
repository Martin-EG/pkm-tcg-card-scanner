"""FAISS index persistence: one exact inner-product index per model and language, plus its id list."""

from __future__ import annotations

import json
from pathlib import Path

import faiss
import numpy as np


def index_paths(index_dir: Path, model: str, lang: str = "en") -> tuple[Path, Path]:
    return index_dir / f"{model}_{lang}.faiss", index_dir / f"{model}_{lang}_ids.json"


def build(vectors: np.ndarray) -> faiss.Index:
    # Vectors are L2-normalized, so inner product == cosine similarity.
    index = faiss.IndexFlatIP(vectors.shape[1])
    index.add(np.ascontiguousarray(vectors, dtype=np.float32))
    return index


def save(index: faiss.Index, ids: list[str], index_dir: Path, model: str, lang: str = "en") -> None:
    index_dir.mkdir(parents=True, exist_ok=True)
    idx_path, ids_path = index_paths(index_dir, model, lang)
    faiss.write_index(index, str(idx_path))
    ids_path.write_text(json.dumps(ids))


def load(index_dir: Path, model: str, lang: str = "en") -> tuple[faiss.Index, list[str]]:
    idx_path, ids_path = index_paths(index_dir, model, lang)
    index = faiss.read_index(str(idx_path))
    ids = json.loads(ids_path.read_text())
    if index.ntotal != len(ids):
        raise ValueError(f"{idx_path}: {index.ntotal} vectors but {len(ids)} ids")
    return index, ids


def search(index: faiss.Index, ids: list[str], query: np.ndarray, k: int) -> list[tuple[str, float]]:
    scores, rows = index.search(np.ascontiguousarray(query.reshape(1, -1), dtype=np.float32), k)
    return [(ids[r], float(s)) for r, s in zip(rows[0], scores[0]) if r >= 0]
