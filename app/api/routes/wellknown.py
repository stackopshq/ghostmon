"""Public `/.well-known/ghostapp.yaml` — the portal discovery document.

Served without authentication: ghostboard fetches it at startup with no bearer
to hydrate its registry. It carries only presentation metadata (no secrets, no
per-user data), so anonymous access is fine.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse

router = APIRouter()

_MANIFEST = Path(__file__).resolve().parents[3] / "static" / "ghostapp.yaml"


@router.get("/.well-known/ghostapp.yaml", include_in_schema=False)
async def ghostapp_manifest() -> FileResponse:
    return FileResponse(_MANIFEST, media_type="application/yaml")
