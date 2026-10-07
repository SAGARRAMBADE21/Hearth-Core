"""
claude_code agents capability.

Implements the uniform agents contract (same surface as xo-space's adapters):

  list_agents()              -> list[dict]
  create_agent(body)         -> dict | JSONResponse
  get_detail(agent_id)       -> dict | None           # None if not ours
  patch(agent_id, body)      -> resp | None           # None if not ours
  delete(agent_id)           -> resp | None           # None if not ours

xo-space's agents are user-created project folders. HEARTH has none: its one
agent is the built-in **migrator** — Claude Code configured by
``config/agents/claude_code/manifest.json`` with the rules in ``prompts.py`` —
and it is changed by editing that manifest, not through the API. So listing and
detail are real, while create / patch / delete answer 405 (not supported in
HEARTH) for the migrator and ``None`` (not ours) for anything else.

Shape mirrors xo-space ``adapters/claude_code/agents.py``.
"""

from __future__ import annotations

from fastapi.responses import JSONResponse

from services.hearth_agent.adapters.claude_code.prompts import MIGRATOR_RULES
from services.hearth_agent.registry.agent_registry import get_agent
from services.storage.layout import workspaces_dir

_BACKEND = "claude_code"
MIGRATOR_ID = "migrator"
_NOT_SUPPORTED = (
    "HEARTH has one built-in agent (the migrator); change it in config/agents/claude_code/manifest.json."
)


def _agent_info() -> dict:
    manifest = get_agent(_BACKEND)
    flags = manifest.flags
    return {
        "name": MIGRATOR_ID,
        "description": "Applies one provider change to a repository and proves it with the repo's own tests.",
        "mode": "primary",
        "tools": list(flags.get("tools") or []) + [f"mcp__{(manifest.raw.get('mcp') or {}).get('server_name', 'hearth')}__*"],
        "permissions": {"rules": [{"deny": t} for t in flags.get("disallowed_tools") or []]},
        "system_prompt": MIGRATOR_RULES,
        "temperature": None,
        "metadata": {
            "backend": _BACKEND,
            "display_name": "Migrator",
            "workspace": str(workspaces_dir()),
            "model": manifest.model_default,
            "builtin": True,
        },
    }


def list_agents() -> list[dict]:
    return [_agent_info()]


def create_agent(body) -> dict | JSONResponse:
    return JSONResponse(status_code=405, content={"detail": _NOT_SUPPORTED})


def get_detail(agent_id: str) -> dict | None:
    if agent_id != MIGRATOR_ID:
        return None
    manifest = get_agent(_BACKEND)
    return {
        "id": MIGRATOR_ID,
        "display_name": "Migrator",
        "description": _agent_info()["description"],
        "workspace": str(workspaces_dir()),
        "model": manifest.model_default,
        "model_raw": manifest.raw.get("model"),
        "identity": {"name": "HEARTH migrator", "emoji": None, "bio": None},
        "config_entry": {"flags": manifest.flags, "mcp": manifest.raw.get("mcp")},
        "agents_defaults": {},
        "workspace_files": {},
        "on_disk": {
            "agent_dir": str(workspaces_dir()),
            "models_catalog": None,
            "auth_state": None,
            "auth_profiles": None,
        },
        "sessions": {"index_path": None, "count": 0, "session_ids": []},
        "backend": _BACKEND,
        "builtin": True,
    }


def patch(agent_id: str, body) -> dict | JSONResponse | None:
    if agent_id != MIGRATOR_ID:
        return None
    return JSONResponse(status_code=405, content={"detail": _NOT_SUPPORTED})


def delete(agent_id: str) -> dict | JSONResponse | None:
    if agent_id != MIGRATOR_ID:
        return None
    return JSONResponse(status_code=405, content={"detail": _NOT_SUPPORTED})
