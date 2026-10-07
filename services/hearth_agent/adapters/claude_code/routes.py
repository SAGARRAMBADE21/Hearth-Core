"""claude_code adapter-owned routes.

Remote Control lifecycle endpoints. Mounted only when claude_code is the active
agent (``routers/hearth_agent/__init__.py`` resolves the active agent's ``routes``
module via ``try_load_capability('routes')``).

  * ``GET  /api/remote-control/status`` → running, enabled, login presence, link
  * ``POST /api/remote-control/start``  → launch (idempotent); 403 while disabled
  * ``POST /api/remote-control/stop``   → stop (idempotent; always allowed)

Shape mirrors xo-space ``adapters/claude_code/routes.py``.
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from services.hearth_agent.adapters.claude_code import remote_control

router = APIRouter()


class RemoteControlStartBody(BaseModel):
    name: str | None = None


@router.get("/api/remote-control/status")
def remote_control_status():
    """Whether a Remote Control session is live, whether it is enabled, login presence and the link."""
    return remote_control.status()


@router.post("/api/remote-control/start")
def remote_control_start(body: RemoteControlStartBody | None = None):
    """Start the Remote Control session (idempotent). Refused with 403 unless the operator enabled it."""
    result = remote_control.start(name=body.name if body else None)
    if result.get("error") == "disabled":
        return JSONResponse(status_code=403, content=result)
    return result


@router.post("/api/remote-control/stop")
def remote_control_stop():
    """Stop the Remote Control session (idempotent)."""
    return remote_control.stop()
