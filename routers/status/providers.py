"""
``GET /providers/status`` — which LLM credential the active agent resolves to:
``{agent, oauth:{claude_code}, api_keys:{anthropic, llm_gateway}}``, enabled providers only.

Shape mirrors xo-space ``routers/status/providers.py``.
"""

from fastapi import APIRouter, HTTPException

from services.hearth_agent.adapters.loader import load_capability
from services.hearth_agent.registry.agent_registry import get_active_agent

router = APIRouter(prefix="/providers", tags=["providers"])


@router.get("/status")
async def providers_status():
    agent = get_active_agent().name
    try:
        mod = load_capability("providers_status", agent=agent)
    except ModuleNotFoundError as exc:
        raise HTTPException(status_code=501, detail={
            "ok": False, "error": f"no providers-status source for agent '{agent}'", "agent": agent,
        }) from exc
    try:
        return await mod.get_providers_status()
    except Exception as e:
        raise HTTPException(status_code=500, detail={
            "ok": False, "error": f"unexpected error: {e}", "agent": agent,
        }) from e
