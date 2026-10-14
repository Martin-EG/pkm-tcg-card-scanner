"""Detect a single card in a photo and warp it to a straight, upright rectangle.

Edge-only contour detection proved fragile on real counter photos: the card's
outline merges with playmat art or binder pockets, and a sleeve edge or glare
often leaves one side without edges. Instead we segment the card as a region
and take the contour of that region:

1. GrabCut on a small copy, seeded with "the card is somewhere inside the
   central 92% of the frame" (the employee frames one card).
2. Largest foreground contour -> convex hull -> 4-corner polygon.
3. Perspective warp of the full-resolution photo to an upright card.
"""

from __future__ import annotations

import cv2
import numpy as np

# Pokémon cards are 63 x 88 mm.
CARD_ASPECT = 63 / 88
OUT_W, OUT_H = 630, 880
# Segmentation runs on a copy this size; the warp uses the full-size photo.
SEGMENT_MAX_SIDE = 320
GRABCUT_ITERATIONS = 3
# Border of the frame treated as background when seeding GrabCut.
SEED_MARGIN = 0.04
# A detected card must cover at least this fraction of the photo.
MIN_AREA_FRACTION = 0.08
# Allowed deviation from the card's width/height ratio (perspective, sleeves).
MAX_ASPECT_ERROR = 0.25


def order_corners(pts: np.ndarray) -> np.ndarray:
    """Return corners ordered top-left, top-right, bottom-right, bottom-left."""
    pts = pts.reshape(4, 2).astype(np.float32)
    center = pts.mean(axis=0)
    angles = np.arctan2(pts[:, 1] - center[1], pts[:, 0] - center[0])
    pts = pts[np.argsort(angles)]  # clockwise in image coordinates, starting anywhere
    start = int(np.argmin(pts.sum(axis=1)))  # top-left has the smallest x + y
    return np.roll(pts, -start, axis=0)


def _side_lengths(quad: np.ndarray) -> tuple[float, float]:
    tl, tr, br, bl = order_corners(quad)
    w = (np.linalg.norm(tr - tl) + np.linalg.norm(br - bl)) / 2
    h = (np.linalg.norm(bl - tl) + np.linalg.norm(br - tr)) / 2
    return float(w), float(h)


def aspect_error(quad: np.ndarray) -> float:
    """Relative difference between the quad's short/long ratio and a card's."""
    w, h = _side_lengths(quad)
    if min(w, h) <= 0:
        return 1.0
    return abs(min(w, h) / max(w, h) - CARD_ASPECT) / CARD_ASPECT


def _foreground_mask(small: np.ndarray) -> np.ndarray:
    h, w = small.shape[:2]
    mask = np.zeros((h, w), np.uint8)
    rect = (int(SEED_MARGIN * w), int(SEED_MARGIN * h), int((1 - 2 * SEED_MARGIN) * w), int((1 - 2 * SEED_MARGIN) * h))
    cv2.setRNGSeed(0)  # GrabCut's GMM init is random; keep crops repeatable
    bg_model = np.zeros((1, 65), np.float64)
    fg_model = np.zeros((1, 65), np.float64)
    cv2.grabCut(small, mask, rect, bg_model, fg_model, GRABCUT_ITERATIONS, cv2.GC_INIT_WITH_RECT)
    fg = np.where((mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD), 255, 0).astype(np.uint8)
    # Drop thin bridges to neighbouring objects.
    return cv2.morphologyEx(fg, cv2.MORPH_OPEN, np.ones((7, 7), np.uint8))


def _quad_from_contour(contour: np.ndarray) -> np.ndarray:
    hull = cv2.convexHull(contour)
    peri = cv2.arcLength(hull, True)
    for eps in (0.02, 0.03, 0.05, 0.08):
        approx = cv2.approxPolyDP(hull, eps * peri, True)
        if len(approx) == 4:
            return approx.reshape(4, 2).astype(np.float32)
    # Rounded corners can leave 5+ points at every tolerance.
    return cv2.boxPoints(cv2.minAreaRect(hull)).astype(np.float32)


def find_card_quad(image: np.ndarray) -> np.ndarray | None:
    """Return the card's 4 corners in `image` coordinates, or None if not found."""
    h, w = image.shape[:2]
    scale = min(1.0, SEGMENT_MAX_SIDE / max(h, w))
    small = cv2.resize(image, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA) if scale < 1 else image
    if small.ndim == 2:
        small = cv2.cvtColor(small, cv2.COLOR_GRAY2BGR)
    contours, _ = cv2.findContours(_foreground_mask(small), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None
    contour = max(contours, key=cv2.contourArea)
    quad = _quad_from_contour(contour)
    area = cv2.contourArea(quad)
    if area < MIN_AREA_FRACTION * small.shape[0] * small.shape[1] or aspect_error(quad) > MAX_ASPECT_ERROR:
        return None
    return quad / scale


def warp_card(image: np.ndarray, quad: np.ndarray) -> np.ndarray:
    """Perspective-warp the quad to an upright OUT_W x OUT_H card."""
    tl, tr, br, bl = order_corners(quad)
    w, h = _side_lengths(quad)
    src = np.array([tl, tr, br, bl], dtype=np.float32)
    if w > h:
        # Card lies sideways: rotate the corner order so the long side is vertical.
        # Whether it ends up upright or upside down is resolved at search time.
        src = np.array([tr, br, bl, tl], dtype=np.float32)
    dst = np.array([[0, 0], [OUT_W - 1, 0], [OUT_W - 1, OUT_H - 1], [0, OUT_H - 1]], dtype=np.float32)
    m = cv2.getPerspectiveTransform(src, dst)
    return cv2.warpPerspective(image, m, (OUT_W, OUT_H), flags=cv2.INTER_AREA)


def crop_card(image: np.ndarray) -> tuple[np.ndarray, bool]:
    """Return (card image, found). Falls back to the full photo when no card is found."""
    quad = find_card_quad(image)
    if quad is None:
        return image, False
    return warp_card(image, quad), True
