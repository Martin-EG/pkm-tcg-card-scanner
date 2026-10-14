"""Detect the cards in a photo and warp each to a straight, upright rectangle.

Single card: edge-only contour detection proved fragile on real counter photos
(the outline merges with playmat art or binder pockets, and a sleeve edge or glare
often leaves one side without edges). Instead we segment the card as a region:

1. GrabCut on a small copy, seeded with "the card is somewhere inside the
   central part of the frame" (the employee frames one card).
2. Largest foreground contour -> convex hull -> 4-corner polygon.
3. Perspective warp of the full-resolution photo to an upright card.

Several cards (binder page, cards laid out on a table): GrabCut can't separate
neighbouring cards, so we look for card-shaped closed outlines in an edge map
(see find_card_quads). When that finds 2 or more cards the photo is treated as
multi-card; otherwise the single-card path above runs.

Photos with no card or too blurry to read raise PhotoError instead of guessing.
"""

from __future__ import annotations

import cv2
import numpy as np

from server.config.rules import rules

_CFG = rules()["crop"]
_QUALITY = rules()["quality"]

CARD_ASPECT = _CFG["card_aspect"]
OUT_W, OUT_H = _CFG["out_width"], _CFG["out_height"]
SEGMENT_MAX_SIDE = _CFG["segment_max_side"]
GRABCUT_ITERATIONS = _CFG["grabcut_iterations"]
# Border of the frame treated as background when seeding GrabCut.
SEED_MARGIN = _CFG["seed_margin"]
# A detected single card must cover at least this fraction of the photo.
MIN_AREA_FRACTION = _CFG["single_min_area_fraction"]
# Allowed deviation from the card's width/height ratio (perspective, sleeves).
MAX_ASPECT_ERROR = _CFG["max_aspect_error"]


class PhotoError(Exception):
    """The photo can't be used; code is machine-readable, message is for the UI."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


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


def sharpness(image: np.ndarray) -> float:
    """Variance of the Laplacian of the grayscale photo at a fixed working size."""
    h, w = image.shape[:2]
    side = _QUALITY["quality_max_side"]
    scale = min(1.0, side / max(h, w))
    small = cv2.resize(image, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA) if scale < 1 else image
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY) if small.ndim == 3 else small
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def _quad_area(quad: np.ndarray) -> float:
    return float(cv2.contourArea(order_corners(quad)))


def _contains(outer: np.ndarray, point: np.ndarray) -> bool:
    return cv2.pointPolygonTest(order_corners(outer).reshape(-1, 1, 2), (float(point[0]), float(point[1])), False) >= 0


def _edge_map(gray: np.ndarray) -> np.ndarray:
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    median = float(np.median(blurred))
    edges = cv2.Canny(blurred, int(max(0, 0.66 * median)), int(min(255, 1.33 * median)))
    # Close small gaps in card outlines (rounded corners, glare).
    return cv2.dilate(edges, np.ones((3, 3), np.uint8), iterations=1)


def _max_corner_deviation(quad: np.ndarray) -> float:
    """Largest difference, in degrees, between a corner angle and 90."""
    pts = order_corners(quad)
    worst = 0.0
    for i in range(4):
        a, b, c = pts[i - 1], pts[i], pts[(i + 1) % 4]
        v1, v2 = a - b, c - b
        cos = float(np.dot(v1, v2) / (np.linalg.norm(v1) * np.linalg.norm(v2) + 1e-9))
        worst = max(worst, abs(np.degrees(np.arccos(np.clip(cos, -1, 1))) - 90))
    return worst


def _edge_support(quad: np.ndarray, edges: np.ndarray) -> float:
    """Share of points sampled along the quad's sides that fall on an edge pixel."""
    pts = order_corners(quad)
    h, w = edges.shape
    hits = total = 0
    for i in range(4):
        a, b = pts[i], pts[(i + 1) % 4]
        n = max(2, int(np.linalg.norm(b - a) / 3))
        for t in np.linspace(0.05, 0.95, n):  # skip the rounded corners
            x, y = (a + t * (b - a)).round().astype(int)
            total += 1
            hits += 0 <= x < w and 0 <= y < h and edges[y, x] > 0
    return hits / total if total else 0.0


def _bright_region_quads(gray: np.ndarray, min_area: float) -> list[np.ndarray]:
    """Cards on a dark binder page: bright regions that fill a card-shaped rectangle.

    In a binder the card's edge and the pocket's edge blur into one another, so the
    edge map rarely closes around a card; but the card is much brighter than the
    plastic and the dark gaps between pockets keep neighbouring cards apart.
    """
    _, mask = cv2.threshold(cv2.GaussianBlur(gray, (9, 9), 0), 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((9, 9), np.uint8))
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    quads = []
    for c in contours:
        area = cv2.contourArea(c)  # filled area: dark artwork inside the card doesn't count against it
        if area < min_area:
            continue
        quad = cv2.boxPoints(cv2.minAreaRect(c)).astype(np.float32)
        if aspect_error(quad) > MAX_ASPECT_ERROR or area < _CFG["multi_min_fill"] * _quad_area(quad):
            continue
        quads.append(quad)
    return quads


def find_card_quads(image: np.ndarray) -> list[np.ndarray]:
    """Card-shaped outlines, in `image` coordinates and reading order.

    Candidates come from closed outlines in an edge map and from bright regions
    (cards on a dark binder page). Drops outlines that contain 2 or more other
    cards (a binder page or a whole sheet has the same 63:88 shape as a card) and
    keeps the outer one of nested outlines (card in a sleeve or a pocket).
    """
    h, w = image.shape[:2]
    scale = min(1.0, _CFG["detect_max_side"] / max(h, w))
    small = cv2.resize(image, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA) if scale < 1 else image
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY) if small.ndim == 3 else small
    photo_area = gray.shape[0] * gray.shape[1]
    edges = _edge_map(gray)
    contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)

    candidates: list[np.ndarray] = []
    for c in contours:
        hull = cv2.convexHull(c)
        hull_area = cv2.contourArea(hull)
        if hull_area < _CFG["multi_min_area_fraction"] * photo_area:
            continue
        peri = cv2.arcLength(hull, True)
        quad = None
        for eps in (0.02, 0.03, 0.05):
            approx = cv2.approxPolyDP(hull, eps * peri, True)
            if len(approx) == 4:
                quad = approx.reshape(4, 2).astype(np.float32)
                break
        if quad is None or aspect_error(quad) > MAX_ASPECT_ERROR:
            continue
        # The outline must fill its quad, not just touch 4 points of it.
        if hull_area < _CFG["multi_min_hull_fill"] * _quad_area(quad):
            continue
        if _max_corner_deviation(quad) > _CFG["multi_max_corner_deviation_deg"]:
            continue
        if _edge_support(quad, edges) < _CFG["multi_min_edge_support"]:
            continue
        candidates.append(quad)
    candidates += _bright_region_quads(gray, _CFG["multi_min_area_fraction"] * photo_area)

    # Largest first; merge duplicates (both sides of the same edge line).
    candidates.sort(key=_quad_area, reverse=True)
    centers = [q.mean(axis=0) for q in candidates]
    contained = [[j for j in range(len(candidates)) if j != i and _contains(candidates[i], centers[j])]
                 for i in range(len(candidates))]
    kept: list[int] = []
    for i in range(len(candidates)):
        inner_cards = {j for j in contained[i] if _quad_area(candidates[j]) < _CFG["multi_inner_card_ratio"] * _quad_area(candidates[i])}
        if len(inner_cards) >= 2:
            continue  # a page or sheet holding several cards
        if any(_contains(candidates[k], centers[i]) for k in kept):
            continue  # nested inside a card already kept
        kept.append(i)
    quads = [candidates[i] for i in kept]

    if quads:
        median_area = float(np.median([_quad_area(q) for q in quads]))
        quads = [q for q in quads if _quad_area(q) >= _CFG["multi_min_relative_area"] * median_area]
        areas = [_quad_area(q) for q in quads]
        if len(quads) >= 2 and max(areas) > _CFG["multi_max_area_ratio"] * min(areas):
            # Cards of one photo are about the same size; mixed sizes mean we caught clutter.
            quads = [q for q in quads if _quad_area(q) >= max(areas) / _CFG["multi_max_area_ratio"]]
    return _reading_order([q / scale for q in quads])


def _reading_order(quads: list[np.ndarray]) -> list[np.ndarray]:
    """Top-to-bottom rows, left-to-right within a row."""
    if not quads:
        return []
    heights = [_side_lengths(q)[1] for q in quads]
    row_gap = 0.5 * float(np.median(heights))
    by_y = sorted(quads, key=lambda q: q[:, 1].mean())
    rows: list[list[np.ndarray]] = [[by_y[0]]]
    for q in by_y[1:]:
        if q[:, 1].mean() - np.mean([r[:, 1].mean() for r in rows[-1]]) > row_gap:
            rows.append([q])
        else:
            rows[-1].append(q)
    return [q for row in rows for q in sorted(row, key=lambda q: q[:, 0].mean())]


def crop_cards(image: np.ndarray) -> list[np.ndarray]:
    """Every card in the photo, warped upright, in reading order.

    Raises PhotoError("blurry") or PhotoError("no_card") instead of returning a guess.
    """
    if sharpness(image) < _QUALITY["min_sharpness"]:
        raise PhotoError("blurry", "La foto está borrosa. Toma otra con el celular quieto y buena luz.")
    quads = find_card_quads(image)
    if len(quads) >= 2:
        return [warp_card(image, q) for q in quads[: _CFG["max_cards"]]]
    quad = find_card_quad(image)
    if quad is None:
        raise PhotoError("no_card", "No se encontró ninguna carta en la foto.")
    return [warp_card(image, quad)]
