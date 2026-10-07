"""
``GET /channels/status`` — `{channels:[...]}` for the active agent (empty for claude_code).

Shape mirrors xo-space ``routers/status/channels.py``.
"""

from fastapi import APIRouter, HTTPException

from services.hearth_agent.adapters.cli_status import CliStatusError
from services.hearth_agent.adapters.loader import load_capability
from services.hearth_agent.registry.agent_registry import get_active_agent

from .models import ERROR_STATUS

router = APIRouter(prefix="/channels", tags=["channels"])


@router.get("/status")
async def channels_status():
    agent = get_active_agent().name
    try:
        mod = load_capability("channels_status", agent=agent)
    except ModuleNotFoundError as exc:
        raise HTTPException(status_code=501, detail={
            "ok": False, "error": f"no live channels-status source for agent '{agent}'", "agent": agent,
        }) from exc
    try:
        return await mod.get_channels_status()
    except CliStatusError as e:
        raise HTTPException(status_code=ERROR_STATUS.get(e.code, 502), detail={
            "ok": False, "error": str(e), "code": e.code, "detail": e.detail, "agent": agent,
        }) from e
