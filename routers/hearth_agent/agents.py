"""
REST routes for the agent framework.

  GET /api/agents               — discovered adapters and the active agent
  GET /api/agents/health        — the active adapter's health (CLI present, version)
  GET /api/agents/capabilities  — the active agent's capabilities.json
"""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from services.hearth_agent.engine.dispatcher import AgentDispatcher
from services.hearth_agent.registry.adapter_registry import list_adapters
from services.hearth_agent.registry.agent_registry import get_active_agent
from services.hearth_agent.registry.settings import load_agent_capabilities

router = APIRouter()


@router.get("/api/agents")
async def agents() -> JSONResponse:
    active = get_active_agent()
    return JSONResponse({"active": active.name, "model": active.model_default, "adapters": list_adapters()})


@router.get("/api/agents/health")
async def agent_health() -> JSONResponse:
    return JSONResponse(await AgentDispatcher().health())


@router.get("/api/agents/capabilities")
async def agent_capabilities() -> JSONResponse:
    return JSONResponse(load_agent_capabilities(get_active_agent().name))
