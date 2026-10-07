"""
``GET /api/models`` — the models a job can run on, from the active agent's ``models`` capability.

Shape mirrors xo-space's ``/api/models`` listing.
"""

from fastapi import APIRouter

from services.hearth_agent.adapters.loader import try_load_capability

router = APIRouter()


@router.get("/api/models")
async def list_models():
    mod = try_load_capability("models")
    return mod.list_models() if mod else []
