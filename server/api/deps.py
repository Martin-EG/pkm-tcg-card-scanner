"""Services shared by the routes, created once at startup (or injected by tests)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import Request

from server.config.settings import Settings
from server.sessions.service import SessionService
from server.storage.db import Store


@dataclass
class Services:
    identifier: Any  # server.recognition.identify.Identifier (heavy; loaded at startup)
    store: Store
    sessions: SessionService
    settings: Settings
    scans_dir: Path


def services(request: Request) -> Services:
    return request.app.state.services
