"""POST /identify (photo -> cards) and POST /corrections (employee's pick)."""

from __future__ import annotations

import io
import time
from pathlib import Path

import cv2
import numpy as np
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from PIL import Image, ImageOps

from server.api.deps import Services, services
from server.api.schemas import Correction
from server.paths import ROOT
from server.recognition.crop import PhotoError

try:  # iPhone photos
    from pillow_heif import register_heif_opener

    register_heif_opener()
except ImportError:
    pass

router = APIRouter()

# Shown with a card whose printed language has no catalog yet.
LANGUAGE_WARNINGS = {
    "es": "Parece una carta en español. Solo hay catálogo en inglés: confirma la carta y el precio a mano.",
    "ja": "Parece una carta en japonés. Solo hay catálogo en inglés: confirma la carta y el precio a mano.",
}


def decode_photo(data: bytes) -> np.ndarray:
    """Bytes of a JPEG/PNG/HEIC photo -> BGR array with the phone's EXIF rotation applied."""
    try:
        with Image.open(io.BytesIO(data)) as im:
            rgb = ImageOps.exif_transpose(im).convert("RGB")
    except Exception as e:  # noqa: BLE001 - any decoder failure means "not a photo"
        raise PhotoError("bad_image", "El archivo no es una foto válida.") from e
    return cv2.cvtColor(np.asarray(rgb), cv2.COLOR_RGB2BGR)


def _fresh_scan_dir(scans_dir: Path, scan_id: int) -> Path:
    """Folder for a new scan's files. A folder already there belongs to another database
    (scan ids restart with a new one), so it's moved to scans/_older/ instead of being
    overwritten."""
    scan_dir = scans_dir / str(scan_id)
    if scan_dir.exists() and any(scan_dir.iterdir()):
        older = scans_dir / "_older"
        older.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(scan_dir.stat().st_mtime))
        scan_dir.rename(older / f"{scan_id}-{stamp}")
    scan_dir.mkdir(parents=True, exist_ok=True)
    return scan_dir


def _rel(path: Path) -> str:
    return str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path)


@router.post("/identify")
async def identify(photo: UploadFile = File(...), svc: Services = Depends(services)):
    t0 = time.perf_counter()
    data = await photo.read()
    store = svc.store
    scan_id = store.add_scan("")
    scan_dir = _fresh_scan_dir(svc.scans_dir, scan_id)
    suffix = Path(photo.filename or "photo.jpg").suffix.lower() or ".jpg"
    photo_path = scan_dir / f"photo{suffix}"
    photo_path.write_bytes(data)
    store.conn.execute("UPDATE scans SET photo_path = ? WHERE id = ?", (_rel(photo_path), scan_id))
    try:
        results = svc.identifier.identify_photo(decode_photo(data))
    except PhotoError as e:
        store.finish_scan(scan_id, time.perf_counter() - t0, e.code)
        raise
    cards = []
    for i, r in enumerate(results):
        crop_path = scan_dir / f"card_{i}.jpg"
        cv2.imwrite(str(crop_path), r.crop)
        candidates = [{
            "id": c.card_id, "name": c.name, "set": c.set_id, "set_name": c.set_name,
            "number": c.number, "language": c.lang,
            # Similarity plus the OCR bonus can pass 1; the app shows 0-1.
            "confidence": round(min(1.0, max(0.0, c.score)), 3), "score": c.score,
            "image_url": f"/images/{c.image_path.split('images/', 1)[-1]}",
        } for c in r.candidates]
        store.add_card(scan_id, i, _rel(crop_path), r.language, candidates[0]["id"] if candidates else None,
                       r.confident, r.ocr_used, candidates)
        cards.append({
            "index": i,
            "language": r.language,
            "confident": r.confident,
            "needs_review": r.needs_review,
            "ocr_used": r.ocr_used,
            "detected_language": r.foreign_language or r.language,
            "warning": LANGUAGE_WARNINGS.get(r.foreign_language),
            "candidates": candidates,
            "crop_url": f"/scans/{scan_id}/card_{i}.jpg",
        })
    seconds = time.perf_counter() - t0
    store.finish_scan(scan_id, seconds)
    return {"scan_id": scan_id, "seconds": round(seconds, 3), "cards": cards}


@router.post("/corrections")
async def corrections(c: Correction, svc: Services = Depends(services)):
    card = svc.store.get_card(c.scan_id, c.card_index)
    if card is None:
        raise HTTPException(404, "No existe esa carta en ese escaneo.")
    catalogs = svc.identifier.catalogs
    if c.language not in catalogs or c.card_id not in catalogs[c.language].rows:
        raise HTTPException(422, "La carta indicada no está en el catálogo.")
    cid = svc.store.add_correction(c.scan_id, c.card_index, c.card_id, c.language, card["top_card_id"])
    return {"correction_id": cid}
