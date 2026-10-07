"""Router aggregation for the hearth_agent subpackage.

Each route module exposes a single ``router: APIRouter``. ``all_routers`` is the
ordered list ``server.py`` uses to mount them onto the FastAPI app.

Shape mirrors xo-space ``routers/cowork_agent/__init__.py``, including mounting
the active agent's own ``routes`` capability when it has one.
"""

from fastapi import APIRouter

from services.hearth_agent.adapters.loader import try_load_capability

from .agents import router as agents_router
from .apidiff import router as apidiff_router
from .connectors.github_cli import router as github_cli_router
from .connectors.github_pat import router as github_pat_router


def _active_agent_routes() -> list[APIRouter]:
    """Mount ``services/hearth_agent/adapters/<AGENT_NAME>/routes.py`` when the agent provides one."""
    mod = try_load_capability("routes")
    router = getattr(mod, "router", None) if mod else None
    return [router] if router is not None else []


all_routers: list[APIRouter] = [
    agents_router,
    *_active_agent_routes(),
    apidiff_router,
    github_pat_router,
    github_cli_router,
]
