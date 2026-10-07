"""
REST routes for agent sessions (one per job), resolved through the active agent's
``sessions`` and ``session_prompts`` capabilities.

  GET   /api/sessions                    — index rows, newest first, with title and creation time
  GET   /api/sessions/{session_id}       — one row
  GET   /api/messages/{session_id}       — the session's transcript messages
  GET   /api/sessions/{session_id}/prompts — per-turn prompts (task, fix-ups, revise instructions)
  PATCH /api/sessions/{session_id}       — set the session's workspace directory

Read from the space only while someone views them; nothing is stored elsewhere (PRD §4).
Shape mirrors xo-space ``routers/cowork_agent/sessions.py``.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from services.hearth_agent.adapters.loader import try_load_capability
from services.hearth_agent.engine import sessions_io

router = APIRouter()


def _sessions():
    mod = try_load_capability("sessions")
    if mod is None:
        raise HTTPException(status_code=501, detail="The active agent does not expose sessions.")
    return mod


@router.get("/api/sessions")
async def list_sessions():
    return _sessions().list_sessions()


@router.get("/api/sessions/{session_id}")
async def get_session(session_id: str):
    try:
        row = sessions_io.read_session_row(session_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if row is None:
        raise HTTPException(status_code=404, detail="Session not found.")
    return {**row, "key": session_id}


@router.get("/api/messages/{session_id}")
async def get_messages(session_id: str):
    mod = _sessions()
    if not mod.owns_session(session_id):
        raise HTTPException(status_code=404, detail="Session not found.")
    return mod.get_messages(session_id)


@router.get("/api/sessions/{session_id}/prompts")
async def get_session_prompts(session_id: str):
    mod = try_load_capability("session_prompts")
    if mod is None:
        raise HTTPException(status_code=501, detail="The active agent does not expose session prompts.")
    try:
        return mod.collect_session_prompts(session_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


class SessionPatch(BaseModel):
    directory: str


@router.patch("/api/sessions/{session_id}")
async def patch_session(session_id: str, body: SessionPatch):
    result = _sessions().set_session_directory(session_id, body.directory)
    if result is None:
        raise HTTPException(status_code=404, detail="Session not found.")
    return result
