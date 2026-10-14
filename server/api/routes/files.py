"""Files: official card images, scan photos and crops, and the shop certificate."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, Response

from server.api.deps import Services, services
from server.paths import CA_CERT, DATA

router = APIRouter()


def _safe_file(base: Path, rel: str) -> FileResponse:
    target = (base / rel).resolve()
    if not target.is_relative_to(base.resolve()) or not target.is_file():
        raise HTTPException(404, "No encontrado.")
    return FileResponse(target)


@router.get("/images/{path:path}")
async def official_image(path: str):
    return _safe_file(DATA / "images", path)


@router.get("/scans/{scan_id}/{name}")
async def scan_file(scan_id: int, name: str, svc: Services = Depends(services)):
    return _safe_file(svc.scans_dir / str(scan_id), name)


@router.get("/certificado")
async def shop_certificate():
    """The shop's certificate authority, to install once on each phone (local HTTPS)."""
    if not CA_CERT.is_file():
        raise HTTPException(404, "Aún no hay certificado. Ejecuta scripts/make_cert.py en la PC de la tienda.")
    return Response(CA_CERT.read_bytes(), media_type="application/x-x509-ca-cert",
                    headers={"Content-Disposition": 'attachment; filename="tienda-ca.crt"'})
