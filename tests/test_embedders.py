import numpy as np
from PIL import Image

from scanner import embedders
from scanner.embedders import ART_WEIGHT, artwork, embed_cards


class FakeEmbedder:
    """Unit vector from the image's mean colour, so different crops give different vectors."""

    name, dim = "fake", 3

    def embed(self, images):
        v = np.array([np.asarray(im, dtype=np.float32).mean(axis=(0, 1)) + 1 for im in images])
        return (v / np.linalg.norm(v, axis=1, keepdims=True)).astype(np.float32)


def two_tone_card(top, bottom):
    card = Image.new("RGB", (630, 880), bottom)
    card.paste(Image.new("RGB", (630, 440), top), (0, 0))
    return card


def test_artwork_box_is_inside_card():
    art = artwork(Image.new("RGB", (630, 880)))
    assert 0 < art.width < 630 and 0 < art.height < 880


def test_combined_vector_is_unit_and_weights_similarity():
    e = FakeEmbedder()
    a = two_tone_card((200, 30, 30), (30, 30, 200))
    b = two_tone_card((200, 30, 30), (200, 200, 200))  # same artwork, different lower half
    va, vb = embed_cards(e, [a, b])
    assert np.isclose(np.linalg.norm(va), 1.0, atol=1e-5)
    whole = e.embed([a, b])
    arts = e.embed([artwork(a), artwork(b)])
    expected = (1 - ART_WEIGHT) * whole[0] @ whole[1] + ART_WEIGHT * arts[0] @ arts[1]
    assert np.isclose(va @ vb, expected, atol=1e-5)
    # The shared artwork pulls the pair closer than whole-card similarity alone.
    assert va @ vb > whole[0] @ whole[1]


def test_art_weight_is_a_fraction():
    assert 0 <= embedders.ART_WEIGHT <= 1
