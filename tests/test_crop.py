import cv2
import numpy as np
import pytest

from scanner.crop import OUT_H, OUT_W, crop_card, find_card_quad, order_corners


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
