"""
``GET /models/status`` — `{default, models:[{id, status}]}` for the active agent.

Dispatches through ``load_capability("models_status")``; an agent without that
capability answers 501. CLI failures map to the codes below.

Shape mirrors xo-space ``routers/status/models.py``.
"""

from fastapi import APIRouter, HTTPException

from services.hearth_agent.adapters.cli_status import CliStatusError
from services.hearth_agent.adapters.loader import load_capability
from services.hearth_agent.registry.agent_registry import get_active_agent

router = APIRouter(prefix="/models", tags=["models"])

ERROR_STATUS = {
    "binary_not_found": 503,
    "timeout": 504,
    "execution_failed": 502,
    "invalid_json": 502,
    "invalid_output": 502,
}


@router.get("/status")
async def models_status():
    agent = get_active_agent().name
    try:
        mod = load_capability("models_status", agent=agent)
    except ModuleNotFoundError as exc:
        raise HTTPException(status_code=501, detail={
            "ok": False, "error": f"no live models-status source for agent '{agent}'", "agent": agent,
        }) from exc
    try:
        return await mod.get_models_status()
    except CliStatusError as e:
        raise HTTPException(status_code=ERROR_STATUS.get(e.code, 502), detail={
            "ok": False, "error": str(e), "code": e.code, "detail": e.detail, "agent": agent,
        }) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail={
            "ok": False, "error": f"unexpected error: {e}", "agent": agent,
        }) from e
