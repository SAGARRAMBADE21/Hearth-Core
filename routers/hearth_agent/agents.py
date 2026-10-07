"""
REST routes for agents.

Uniform agents contract, resolved through the active agent's ``agents`` capability
(shape mirrors xo-space ``routers/cowork_agent/agents.py``):

  GET    /api/agents               — the agent list (HEARTH: the built-in migrator)
  POST   /api/agents               — create (claude_code answers 405: not supported)
  GET    /api/agents/{agent_id}    — detail, 404 if no adapter owns it
  PATCH  /api/agents/{agent_id}    — update (405 for the migrator)
  DELETE /api/agents/{agent_id}    — delete (405 for the migrator)

Runtime info for the agent framework itself:

  GET /api/agents/runtime       — active agent, its model, discovered adapters
  GET /api/agents/health        — the active adapter's health (CLI present, version)
  GET /api/agents/capabilities  — the active agent's capabilities.json
"""

from typing import Any

from fastapi import APIRouter, Body
from fastapi.responses import JSONResponse

from services.hearth_agent.adapters.loader import try_load_capability
from services.hearth_agent.engine.dispatcher import AgentDispatcher
from services.hearth_agent.registry.adapter_registry import list_adapters
from services.hearth_agent.registry.agent_registry import get_active_agent
from services.hearth_agent.registry.settings import load_agent_capabilities

router = APIRouter()

_NOT_FOUND = JSONResponse(status_code=404, content={"detail": "Not found"})


def _agents_capability():
    return try_load_capability("agents")


# Fixed paths first, so "runtime" / "health" / "capabilities" never match {agent_id}.

@router.get("/api/agents/runtime")
async def agents_runtime() -> JSONResponse:
    active = get_active_agent()
    return JSONResponse({"active": active.name, "model": active.model_default, "adapters": list_adapters()})


@router.get("/api/agents/health")
async def agent_health() -> JSONResponse:
    return JSONResponse(await AgentDispatcher().health())


@router.get("/api/agents/capabilities")
async def agent_capabilities() -> JSONResponse:
    return JSONResponse(load_agent_capabilities(get_active_agent().name))


@router.get("/api/agents")
async def list_agents() -> JSONResponse:
    mod = _agents_capability()
    return JSONResponse(mod.list_agents() if mod else [])


@router.post("/api/agents")
async def create_agent(body: dict[str, Any] = Body(default_factory=dict)):
    mod = _agents_capability()
    if mod is None:
        return JSONResponse(status_code=501, content={"detail": "The active agent does not support agents."})
    return mod.create_agent(body)


@router.get("/api/agents/{agent_id}")
async def get_agent_detail(agent_id: str):
    mod = _agents_capability()
    detail = mod.get_detail(agent_id) if mod else None
    return detail if detail is not None else _NOT_FOUND


@router.patch("/api/agents/{agent_id}")
async def patch_agent(agent_id: str, body: dict[str, Any] = Body(default_factory=dict)):
    mod = _agents_capability()
    result = mod.patch(agent_id, body) if mod else None
    return result if result is not None else _NOT_FOUND


@router.delete("/api/agents/{agent_id}")
async def delete_agent(agent_id: str):
    mod = _agents_capability()
    result = mod.delete(agent_id) if mod else None
    return result if result is not None else _NOT_FOUND
