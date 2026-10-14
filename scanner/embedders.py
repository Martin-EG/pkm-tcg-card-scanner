"""Image embedding models. All run on CPU and return L2-normalized float32 vectors."""

from __future__ import annotations

from typing import Protocol

import numpy as np
import torch
from PIL import Image

MODELS = ("clip", "dinov2")

# Card images are squashed to a square instead of center-cropped, so the whole card
# (name bar, art, set number) is always seen. Catalog and query use the same transform.
_MEAN = {
    "clip": (0.48145466, 0.4578275, 0.40821073),
    "dinov2": (0.485, 0.456, 0.406),
}
_STD = {
    "clip": (0.26862954, 0.26130258, 0.27577711),
    "dinov2": (0.229, 0.224, 0.225),
}


class Embedder(Protocol):
    name: str
    dim: int

    def embed(self, images: list[Image.Image]) -> np.ndarray: ...


def _to_tensor(images: list[Image.Image], size: tuple[int, int], mean, std) -> torch.Tensor:
    arrs = []
    for im in images:
        im = im.convert("RGB").resize(size, Image.BICUBIC)
        arrs.append(np.asarray(im, dtype=np.float32) / 255.0)
    x = torch.from_numpy(np.stack(arrs)).permute(0, 3, 1, 2)
    m = torch.tensor(mean).view(1, 3, 1, 1)
    s = torch.tensor(std).view(1, 3, 1, 1)
    return (x - m) / s


def _normalize(v: torch.Tensor) -> np.ndarray:
    v = torch.nn.functional.normalize(v.float(), dim=-1)
    return v.cpu().numpy().astype(np.float32)


class ClipEmbedder:
    """OpenAI CLIP ViT-B/32 image tower via open_clip."""

    name = "clip"

    def __init__(self, arch: str = "ViT-B-32-quickgelu", pretrained: str = "openai"):
        import open_clip

        self.model, _, _ = open_clip.create_model_and_transforms(arch, pretrained=pretrained)
        self.model.eval()
        self.size = (224, 224)
        self.dim = self.model.visual.output_dim

    @torch.inference_mode()
    def embed(self, images: list[Image.Image]) -> np.ndarray:
        x = _to_tensor(images, self.size, _MEAN["clip"], _STD["clip"])
        return _normalize(self.model.encode_image(x))


class Dinov2Embedder:
    """Meta DINOv2 ViT-B/14; CLS token concatenated with mean patch token."""

    name = "dinov2"

    def __init__(self, repo: str = "facebook/dinov2-base"):
        from transformers import AutoModel

        self.model = AutoModel.from_pretrained(repo)
        self.model.eval()
        self.size = (224, 224)
        self.dim = self.model.config.hidden_size * 2

    @torch.inference_mode()
    def embed(self, images: list[Image.Image]) -> np.ndarray:
        x = _to_tensor(images, self.size, _MEAN["dinov2"], _STD["dinov2"])
        h = self.model(pixel_values=x).last_hidden_state
        cls = torch.nn.functional.normalize(h[:, 0], dim=-1)
        patch = torch.nn.functional.normalize(h[:, 1:].mean(dim=1), dim=-1)
        return _normalize(torch.cat([cls, patch], dim=-1))


def load_embedder(name: str) -> Embedder:
    if name == "clip":
        return ClipEmbedder()
    if name == "dinov2":
        return Dinov2Embedder()
    raise ValueError(f"unknown model {name!r}; choose from {MODELS}")


# The artwork box of a modern card, as (left, top, right, bottom) fractions.
# Reverse-holo foil, promo stamps, and imperfect crops change the rest of the card
# but not the artwork, so it gets an embedding of its own.
ART_BOX = (0.08, 0.10, 0.92, 0.52)
# Share of the similarity score that comes from the artwork box.
ART_WEIGHT = 0.5


def artwork(card: Image.Image) -> Image.Image:
    w, h = card.size
    left, top, right, bottom = ART_BOX
    return card.crop((int(left * w), int(top * h), int(right * w), int(bottom * h)))


def embed_cards(embedder: Embedder, cards: list[Image.Image]) -> np.ndarray:
    """Whole card and artwork box, weighted and concatenated into one unit vector.

    Inner product of two such vectors = (1 - ART_WEIGHT) * card similarity
    + ART_WEIGHT * artwork similarity.
    """
    cards = [c.convert("RGB") for c in cards]
    vecs = embedder.embed(cards + [artwork(c) for c in cards])
    whole, art = vecs[: len(cards)], vecs[len(cards) :]
    return np.ascontiguousarray(
        np.hstack([np.sqrt(1 - ART_WEIGHT) * whole, np.sqrt(ART_WEIGHT) * art]), dtype=np.float32
    )
