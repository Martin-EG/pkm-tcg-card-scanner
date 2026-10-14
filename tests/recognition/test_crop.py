import cv2
import numpy as np
import pytest

from server.recognition.crop import OUT_H, OUT_W, crop_card, find_card_quad, order_corners


def synthetic_card(w=630, h=880):
    """A card-like image: yellow border, blue art box, and a dark name bar."""
    card = np.full((h, w, 3), (40, 200, 240), np.uint8)  # yellow border (BGR)
    cv2.rectangle(card, (40, 40), (w - 40, h - 40), (230, 230, 230), -1)
    cv2.rectangle(card, (60, 120), (w - 60, 480), (200, 80, 30), -1)  # art
    cv2.rectangle(card, (60, 60), (w - 60, 100), (30, 30, 30), -1)  # name bar
    return card


def place_on_background(card, angle_deg=0.0, bg=(90, 110, 100), size=(1600, 1200), tilt=0):
    """Put the card on a plain background with rotation and a little perspective."""
    H, W = size[1], size[0]
    photo = np.full((H, W, 3), bg, np.uint8)
    noise = np.random.default_rng(0).integers(0, 15, photo.shape, dtype=np.uint8)
    photo = cv2.add(photo, noise)
    h, w = card.shape[:2]
    src = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
    c = np.array([W / 2, H / 2])
    scale = 0.55 * H / h
    a = np.deg2rad(angle_deg)
    rot = np.array([[np.cos(a), -np.sin(a)], [np.sin(a), np.cos(a)]])
    dst = (src - [w / 2, h / 2]) * scale @ rot.T + c
    dst[0] += [tilt, 0]
    dst[1] -= [tilt, 0]
    m = cv2.getPerspectiveTransform(src, dst.astype(np.float32))
    warped = cv2.warpPerspective(card, m, (W, H))
    mask = cv2.warpPerspective(np.full((h, w), 255, np.uint8), m, (W, H))
    photo[mask > 0] = warped[mask > 0]
    return photo, dst


def test_order_corners():
    pts = np.float32([[10, 100], [100, 100], [10, 0], [100, 0]])
    tl, tr, br, bl = order_corners(pts)
    assert tuple(tl) == (10, 0) and tuple(tr) == (100, 0)
    assert tuple(br) == (100, 100) and tuple(bl) == (10, 100)


@pytest.mark.parametrize("angle,tilt", [(0, 0), (12, 0), (-20, 30), (90, 0), (5, 60)])
def test_finds_card_and_corners(angle, tilt):
    photo, true_corners = place_on_background(synthetic_card(), angle, tilt=tilt)
    quad = find_card_quad(photo)
    assert quad is not None
    got = order_corners(quad)
    want = order_corners(true_corners)
    # Corners within 3% of the photo height.
    assert np.abs(got - want).max() < 0.03 * photo.shape[0]


def test_crop_output_is_upright_card():
    card = synthetic_card()
    photo, _ = place_on_background(card, 8)
    out, found = crop_card(photo)
    assert found
    assert out.shape[:2] == (OUT_H, OUT_W)
    # The art box (blue) should land where it is on the original card.
    diff = cv2.absdiff(cv2.resize(out, (OUT_W, OUT_H)), card).mean()
    assert diff < 25


def test_sideways_card_is_warped_portrait():
    photo, _ = place_on_background(synthetic_card(), 90)
    out, found = crop_card(photo)
    assert found and out.shape[:2] == (OUT_H, OUT_W)


def test_no_card_falls_back_to_full_photo():
    photo = np.full((800, 600, 3), 128, np.uint8)
    out, found = crop_card(photo)
    assert not found
    assert out is photo


# --- Multi-card photos and photo errors ---------------------------------------------

import server.recognition.crop as crop_module  # noqa: E402
from server.recognition.crop import PhotoError, crop_cards  # noqa: E402


def colored_card(i: int, w=630, h=880):
    """synthetic_card with a different art color per card, so order can be checked."""
    card = synthetic_card(w, h)
    color = [(200, 80, 30), (30, 160, 60), (40, 40, 200), (160, 40, 160), (20, 160, 200),
             (120, 120, 20), (90, 30, 30), (200, 200, 60), (60, 60, 60)][i % 9]
    cv2.rectangle(card, (60, 120), (w - 60, 480), color, -1)
    return card


def binder_page(rows=3, cols=3, card_h=300, gap=36, margin=60, pockets=True):
    """Cards in a grid on a dark page, optionally with visible pocket outlines."""
    card_w = int(card_h * 63 / 88)
    W = margin * 2 + cols * card_w + (cols - 1) * gap
    H = margin * 2 + rows * card_h + (rows - 1) * gap
    page = np.full((H, W, 3), (35, 35, 40), np.uint8)
    page = cv2.add(page, np.random.default_rng(1).integers(0, 12, page.shape, dtype=np.uint8))
    for r in range(rows):
        for c in range(cols):
            x = margin + c * (card_w + gap)
            y = margin + r * (card_h + gap)
            if pockets:
                cv2.rectangle(page, (x - 10, y - 10), (x + card_w + 10, y + card_h + 10), (90, 90, 95), 2)
            card = cv2.resize(colored_card(r * cols + c), (card_w, card_h), interpolation=cv2.INTER_AREA)
            page[y:y + card_h, x:x + card_w] = card
    return page


def art_color(card):
    return card[300, OUT_W // 2].astype(int)


@pytest.mark.parametrize("pockets", [False, True])
def test_binder_page_gives_nine_cards_in_reading_order(pockets):
    cards = crop_cards(binder_page(pockets=pockets))
    assert len(cards) == 9
    for i, card in enumerate(cards):
        assert card.shape[:2] == (OUT_H, OUT_W)
        want = np.array(colored_card(i)[300, 315], int)
        assert np.abs(art_color(card) - want).max() < 40, f"card {i} out of order"


def test_two_cards_on_a_table():
    cards = crop_cards(binder_page(rows=1, cols=2, card_h=500, gap=120, pockets=False))
    assert len(cards) == 2


def test_single_card_still_uses_single_path(monkeypatch):
    # The flat synthetic photo is far smoother than a real one; only the crop path is under test.
    monkeypatch.setitem(crop_module._QUALITY, "min_sharpness", 0.0)
    photo, _ = place_on_background(synthetic_card(), 8)
    assert len(crop_cards(photo)) == 1


def test_no_card_raises():
    with pytest.raises(PhotoError) as e:
        crop_cards(cv2.add(np.full((800, 600, 3), 128, np.uint8),
                           np.random.default_rng(2).integers(0, 30, (800, 600, 3), dtype=np.uint8)))
    assert e.value.code == "no_card"


def test_blurry_photo_raises():
    photo, _ = place_on_background(synthetic_card(), 8)
    with pytest.raises(PhotoError) as e:
        crop_cards(cv2.GaussianBlur(photo, (0, 0), 12))
    assert e.value.code == "blurry"
