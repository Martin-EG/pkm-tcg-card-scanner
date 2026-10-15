"""FastAPI app: wires the services together and mounts the routes and the phone app."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from server.api.deps import Services
from server.api.routes import files as files_routes
from server.api.routes import identify as identify_routes
from server.api.routes import sessions as sessions_routes
from server.api.routes import settings as settings_routes
from server.config.rules import fx_rules, pricing_rules
from server.config.settings import Settings, get_settings
from server.paths import APP_DIST, DATA, DB_PATH, SCANS_DIR
from server.pricing.fx import BanxicoClient, FxService, FxUnavailable
from server.pricing.prices import PriceService, build_providers
from server.recognition.crop import PhotoError
from server.sessions.service import SessionError, SessionService
from server.storage.db import Store


def build_sessions(store: Store, identifier, settings: Settings) -> SessionService:
    """Price, exchange rate, and session services wired to the real APIs."""
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


def create_app(identifier=None, store: Store | None = None, scans_dir: Path = SCANS_DIR,
               sessions: SessionService | None = None, settings: Settings | None = None,
               app_dist: Path = APP_DIST) -> FastAPI:
    """Services can be injected for tests; by default they load at startup."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        nonlocal identifier, store, sessions, settings
        if identifier is None:
            from server.recognition.identify import Identifier  # loads the models: seconds

            identifier = Identifier(get_settings().languages)
        store = store or Store(DB_PATH)
        settings = settings or get_settings()
        sessions = sessions or build_sessions(store, identifier, settings)
        app.state.services = Services(identifier, store, sessions, settings, scans_dir)
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

    for routes in (identify_routes, sessions_routes, settings_routes, files_routes):
        app.include_router(routes.router)

    if app_dist.is_dir():
        # Mounted last so the API routes win; html=True serves index.html at "/".
        app.mount("/", StaticFiles(directory=app_dist, html=True), name="app")
    return app
