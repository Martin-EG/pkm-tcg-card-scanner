"""Buy sessions: /sessions and their cards."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from server.api.deps import Services, services
from server.api.schemas import SessionCardIn, SessionCardPatch
from server.sessions.service import CardInput

router = APIRouter(prefix="/sessions")


@router.post("", status_code=201)
async def create_session(svc: Services = Depends(services)):
    return svc.sessions.create()


@router.get("/{session_id}")
async def get_session(session_id: int, svc: Services = Depends(services)):
    return svc.sessions.get(session_id)


@router.post("/{session_id}/cards", status_code=201)
async def add_session_card(session_id: int, card: SessionCardIn, svc: Services = Depends(services)):
    return svc.sessions.add_card(session_id, CardInput(**card.model_dump()))


@router.patch("/{session_id}/cards/{card_row_id}")
async def update_session_card(session_id: int, card_row_id: int, patch: SessionCardPatch,
                              svc: Services = Depends(services)):
    return svc.sessions.update_card(session_id, card_row_id, patch.model_dump(exclude_unset=True))
