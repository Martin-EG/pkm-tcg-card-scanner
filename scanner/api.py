"""HTTP API for the counter app.

Run on the shop PC:
    uvicorn scanner.api:app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import time
from contextlib import asynccontextmanager
from pathlib import Path

import cv2
import numpy as np
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageOps
from pydantic import BaseModel

from scanner.catalog import DATA, ROOT
from scanner.crop import PhotoError
from scanner.db import Store
from scanner.pricing.fx import FxUnavailable
from scanner.pricing.rules import pricing_rules
from scanner.sessions import CardInput, SessionError, SessionService
from scanner.settings import Settings, get_settings

try:  # iPhone photos
    from pillow_heif import register_heif_opener

    register_heif_opener()
except ImportError:
    pass

SCANS_DIR = DATA / "scans"
CA_CERT = DATA / "certs" / "ca.pem"
# Built counter app (cd app && npm run build).
APP_DIST = ROOT / "app" / "dist"
# Shown with a card whose printed language has no catalog yet.
LANGUAGE_WARNINGS = {
    "es": "Parece una carta en español. Solo hay catálogo en inglés: confirma la carta y el precio a mano.",
    "ja": "Parece una carta en japonés. Solo hay catálogo en inglés: confirma la carta y el precio a mano.",
}


class Correction(BaseModel):
    scan_id: int
    card_index: int
    card_id: str
    language: str = "en"


class SessionCardIn(BaseModel):
    card_id: str
    catalog_language: str = "en"
    # detected_language from /identify when the card is printed in Spanish or Japanese.
    printed_language: str | None = None
    scan_id: int | None = None
    card_index: int | None = None


class SessionCardPatch(BaseModel):
    condition: str | None = None
    variant: str | None = None
    # US dollars, as eBay shows them; null goes back to the automatic price.
    manual_price_usd: float | None = None
    accepted: bool | None = None


def build_sessions(store: Store, identifier, settings: Settings) -> SessionService:
    """Price, exchange rate, and session services wired to the real APIs."""
    import json

    from scanner.pricing.fx import BanxicoClient, FxService
    from scanner.pricing.prices import PriceService, build_providers
    from scanner.pricing.rules import fx_rules

    rows = identifier.catalogs["en"].rows
    tcgdex_sets = json.loads((DATA / "cache" / "sets_en.json").read_text(encoding="utf-8"))
    providers = build_providers(pricing_rules().price_sources, rows, tcgdex_sets,
                                DATA / "cache" / "ptcg_sets.json", settings.pokemontcg_api_key)
    prices = PriceService(store.conn, providers)
    fx = None
    if settings.convert_to_mxn:
        fx = FxService(store.conn, BanxicoClient(settings.banxico_token), fx_rules().series,
                       fx_rules().refresh_hours)
    return SessionService(store.conn, prices, fx, pricing_rules(), rows)


def decode_photo(data: bytes) -> np.ndarray:
    """Bytes of a JPEG/PNG/HEIC photo -> BGR array with the phone's EXIF rotation applied."""
    import io

    try:
        with Image.open(io.BytesIO(data)) as im:
            rgb = ImageOps.exif_transpose(im).convert("RGB")
    except Exception as e:  # noqa: BLE001 - any decoder failure means "not a photo"
        raise PhotoError("bad_image", "El archivo no es una foto válida.") from e
    return cv2.cvtColor(np.asarray(rgb), cv2.COLOR_RGB2BGR)


def create_app(identifier=None, store: Store | None = None, scans_dir: Path = SCANS_DIR,
               sessions: SessionService | None = None, settings: Settings | None = None,
               app_dist: Path = APP_DIST) -> FastAPI:
    """Services can be injected for tests; by default they load at startup."""
    state: dict = {"identifier": identifier, "store": store, "sessions": sessions, "settings": settings}

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        if state["identifier"] is None:
            from scanner.identify import Identifier

            state["identifier"] = Identifier(get_settings().languages)
        if state["store"] is None:
            state["store"] = Store(DATA / "scanner.db")
        if state["settings"] is None:
            state["settings"] = get_settings()
        if state["sessions"] is None:
            state["sessions"] = build_sessions(state["store"], state["identifier"], state["settings"])
        yield

    app = FastAPI(title="TCG Buylist Scanner", lifespan=lifespan)

    @app.exception_handler(PhotoError)
    async def photo_error(_request, exc: PhotoError):
        return JSONResponse(status_code=422, content={"error": exc.code, "message": exc.message})

    @app.exception_handler(SessionError)
    async def session_error(_request, exc: SessionError):
        return JSONResponse(status_code=exc.status, content={"error": "session", "message": exc.message})

    @app.exception_handler(FxUnavailable)
    async def fx_error(_request, exc: FxUnavailable):
        return JSONResponse(status_code=503, content={"error": "fx_unavailable", "message": str(exc)})

    @app.get("/settings")
    async def settings_view():
        s: Settings = state["settings"]
        r = pricing_rules()
        return {
            "languages": list(state["identifier"].languages),
            "convert_to_mxn": s.convert_to_mxn,
            "currency": s.currency,
            "conditions": [{"code": c, "factor": f} for c, f in r.condition_factors.items()],
            "default_condition": r.default_condition,
            "cash_pct": r.cash_pct,
            "credit_pct": r.credit_pct,
            "min_offer": r.min_offer[s.currency.lower()],
        }

    @app.post("/sessions", status_code=201)
    async def create_session():
        return state["sessions"].create()

    @app.get("/sessions/{session_id}")
    async def get_session(session_id: int):
        return state["sessions"].get(session_id)

    @app.post("/sessions/{session_id}/cards", status_code=201)
    async def add_session_card(session_id: int, card: SessionCardIn):
        return state["sessions"].add_card(session_id, CardInput(**card.model_dump()))

    @app.patch("/sessions/{session_id}/cards/{card_row_id}")
    async def update_session_card(session_id: int, card_row_id: int, patch: SessionCardPatch):
        return state["sessions"].update_card(session_id, card_row_id, patch.model_dump(exclude_unset=True))

    @app.post("/identify")
    async def identify(photo: UploadFile = File(...)):
        t0 = time.perf_counter()
        data = await photo.read()
        store: Store = state["store"]
        scan_id = store.add_scan("")
        scan_dir = scans_dir / str(scan_id)
        scan_dir.mkdir(parents=True, exist_ok=True)
        suffix = Path(photo.filename or "photo.jpg").suffix.lower() or ".jpg"
        photo_path = scan_dir / f"photo{suffix}"
        photo_path.write_bytes(data)
        store.conn.execute("UPDATE scans SET photo_path = ? WHERE id = ?", (_rel(photo_path), scan_id))
        try:
            results = state["identifier"].identify_photo(decode_photo(data))
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

    @app.post("/corrections")
    async def corrections(c: Correction):
        store: Store = state["store"]
        card = store.get_card(c.scan_id, c.card_index)
        if card is None:
            raise HTTPException(404, "No existe esa carta en ese escaneo.")
        ident = state["identifier"]
        if c.language not in ident.catalogs or c.card_id not in ident.catalogs[c.language].rows:
            raise HTTPException(422, "La carta indicada no está en el catálogo.")
        cid = store.add_correction(c.scan_id, c.card_index, c.card_id, c.language, card["top_card_id"])
        return {"correction_id": cid}

    @app.get("/images/{path:path}")
    async def official_image(path: str):
        return _safe_file(DATA / "images", path)

    @app.get("/scans/{scan_id}/{name}")
    async def scan_file(scan_id: int, name: str):
        return _safe_file(scans_dir / str(scan_id), name)

    @app.get("/certificado")
    async def shop_certificate():
        """The shop's certificate authority, to install once on each phone (local HTTPS)."""
        if not CA_CERT.is_file():
            raise HTTPException(404, "Aún no hay certificado. Ejecuta scripts/make_cert.py en la PC de la tienda.")
        return Response(CA_CERT.read_bytes(), media_type="application/x-x509-ca-cert",
                        headers={"Content-Disposition": 'attachment; filename="tienda-ca.crt"'})

    if app_dist.is_dir():
        # Mounted last so the API routes above win; html=True serves index.html at "/".
        app.mount("/", StaticFiles(directory=app_dist, html=True), name="app")

    return app


def _rel(path: Path) -> str:
    return str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path)


def _safe_file(base: Path, rel: str) -> FileResponse:
    target = (base / rel).resolve()
    if not target.is_relative_to(base.resolve()) or not target.is_file():
        raise HTTPException(404, "No encontrado.")
    return FileResponse(target)


app = create_app()
