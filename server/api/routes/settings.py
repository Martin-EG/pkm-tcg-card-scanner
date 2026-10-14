"""GET /settings: what the phone app needs to know about this server (read-only)."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from server.api.deps import Services, services
from server.config.rules import pricing_rules

router = APIRouter()


@router.get("/settings")
async def settings_view(svc: Services = Depends(services)):
    s, r = svc.settings, pricing_rules()
    return {
        "languages": list(svc.identifier.languages),
        "convert_to_mxn": s.convert_to_mxn,
        "currency": s.currency,
        "conditions": [{"code": c, "factor": f} for c, f in r.condition_factors.items()],
        "default_condition": r.default_condition,
        "cash_pct": r.cash_pct,
        "credit_pct": r.credit_pct,
        "min_offer": r.min_offer[s.currency.lower()],
    }
