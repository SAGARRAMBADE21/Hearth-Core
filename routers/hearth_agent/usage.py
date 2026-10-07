"""
REST routes for agent usage (PRD §5: cost per run, monthly budget), resolved
through ``engine.usage_loader.load_usage_module()``.

  GET /api/usage?days=30           — dashboard: totals, per day, per model, costliest jobs
  GET /api/usage/analytics?days=   — per-day and per-model breakdowns
  GET /api/usage/summary?days=     — totals
  GET /api/usage/summary/card?days= — sessions, tokens, cost
  GET /api/usage/sessions          — every job's usage row
  GET /api/usage/sessions/{id}     — one job's summary from its transcript

Shape mirrors xo-space ``routers/cowork_agent/usage.py``.
"""

from fastapi import APIRouter, HTTPException, Query

from services.hearth_agent.engine.usage_loader import load_usage_module

router = APIRouter()


def _usage():
    try:
        return load_usage_module()
    except ModuleNotFoundError as exc:
        raise HTTPException(status_code=501, detail="The active agent does not report usage.") from exc


@router.get("/api/usage")
async def usage_dashboard(days: int = Query(30, ge=1, le=366)):
    return _usage().dashboard(window={"days": days})


@router.get("/api/usage/analytics")
async def usage_analytics(days: int = Query(30, ge=1, le=366)):
    return _usage().analytics(window={"days": days})


@router.get("/api/usage/summary")
async def usage_summary(days: int = Query(30, ge=1, le=366)):
    return _usage().summary(window={"days": days})


@router.get("/api/usage/summary/card")
async def usage_summary_card(days: int = Query(30, ge=1, le=366)):
    return _usage().summary_card(window={"days": days})


@router.get("/api/usage/sessions")
async def usage_sessions():
    return _usage().list_sessions()


@router.get("/api/usage/sessions/{session_id}")
async def usage_session(session_id: str):
    try:
        result = _usage().get_session(session_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="Session not found.")
    return result
