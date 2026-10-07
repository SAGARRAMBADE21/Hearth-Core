"""
Claude Code sessions capability.

Message reading and session-directory updates for claude_code sessions. A
session is one HEARTH job's agent run; its row lives in the session index
(``engine/sessions_io``) and its transcript at
``<config>/projects/<encoded-cwd>/<nativeSessionId>.jsonl``. Transcripts are read
through the Claude Agent SDK (``get_session_messages`` / ``get_session_info``) so
HEARTH follows the CLI's own file layout instead of re-deriving it.

The listing-side hooks (``enrich_project_session`` / ``resolve_native_file`` /
``list_native_sessions`` / ``USES_PROJECT_SESSIONS``) keep the names of
xo-space's contract so the generic sessions route needs no claude_code branch.

Shape mirrors xo-space ``adapters/claude_code/sessions.py``.
"""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

from services.hearth_agent.adapters.claude_code._project_encoding import projects_dir, transcript_dir
from services.hearth_agent.engine import sessions_io as _session_index

# claude_code publishes its session metadata into the session index.
USES_PROJECT_SESSIONS = True

# The ``backend`` tag every row claude_code publishes carries.
_BACKEND = "claude_code"


def _native_file(native_session_id: str, directory: str) -> Path | None:
    """Path to a Claude Code transcript, or None if absent.

    Looks in the folder the CLI derives from ``directory`` first, then scans one
    level (the sandbox may have been renamed or removed since).
    """
    if not native_session_id:
        return None
    if directory:
        path = transcript_dir(directory) / f"{native_session_id}.jsonl"
        if path.exists():
            return path
    root = projects_dir()
    if not root.is_dir():
        return None
    matches = [c for e in root.iterdir() if e.is_dir() and (c := e / f"{native_session_id}.jsonl").is_file()]
    return max(matches, key=lambda p: p.stat().st_mtime_ns) if matches else None


def _row(session_id: str) -> dict | None:
    row = _session_index.read_session_row(session_id)
    if row and row.get("backend", _BACKEND) == _BACKEND:
        return row
    return None


def enrich_project_session(meta: dict, key: str, default_agent: str):
    """Return ``(time_created, title, effective_agent)`` for an indexed session from its transcript."""
    from claude_agent_sdk import get_session_info

    time_created = None
    title = None
    native = meta.get("nativeSessionId") or ""
    if native:
        try:
            info = get_session_info(native, directory=meta.get("directory") or None)
        except Exception:
            info = None
        if info is not None:
            time_created = info.created_at
            title = info.custom_title or info.summary or info.first_prompt
    return time_created, title, default_agent


def resolve_native_file(meta: dict, session_id: str) -> Path | None:
    """Locate the transcript for an indexed claude_code session."""
    return _native_file(meta.get("nativeSessionId", ""), meta.get("directory", ""))


def list_native_sessions() -> list[dict]:
    """claude_code has no session store outside the index."""
    return []


def owns_session(session_id: str) -> bool:
    """True when the index holds a claude_code row for ``session_id``."""
    return _row(session_id) is not None


def list_sessions() -> list[dict]:
    """Index rows, newest first, each enriched with its transcript's creation time and title."""
    out: list[dict] = []
    for key, meta in _session_index.iter_session_rows():
        if meta.get("backend", _BACKEND) != _BACKEND:
            continue
        time_created, title, _ = enrich_project_session(meta, key, _BACKEND)
        out.append({**meta, "key": key, "timeCreated": time_created, "title": title})
    return out


def _message_dict(msg: Any) -> dict:
    data = asdict(msg) if is_dataclass(msg) else dict(msg)
    inner = data.get("message") or {}
    return {
        "id": data.get("uuid"),
        "role": data.get("type"),  # "user" | "assistant"
        "session_id": data.get("session_id"),
        "content": inner.get("content") if isinstance(inner, dict) else inner,
        "model": inner.get("model") if isinstance(inner, dict) else None,
        "parent_tool_use_id": data.get("parent_tool_use_id"),
    }


def get_messages(session_id: str) -> list:
    """Return the session's messages (empty if it is not ours or has no transcript)."""
    from claude_agent_sdk import get_session_messages

    row = _row(session_id)
    if not row or not row.get("nativeSessionId"):
        return []
    try:
        messages = get_session_messages(row["nativeSessionId"], directory=row.get("directory") or None)
    except Exception:
        return []
    return [_message_dict(m) for m in messages]


def _persist_session_directory(session_id: str, directory: str) -> bool:
    row = _row(session_id)
    if row is None:
        return False
    now_ms = _session_index.now_ms()
    history = list(row.get("directoryHistory") or [])
    history.append({"directory": directory, "selectedAt": now_ms})
    row["directoryHistory"] = history[-200:]
    row["directory"] = directory
    row["updatedAt"] = now_ms
    return _session_index.write_session_row(session_id, row)


def set_session_directory(session_id: str, directory: str) -> dict | None:
    """Set the workspace directory for a claude_code session; None if not ours."""
    if _persist_session_directory(session_id, directory):
        return {"ok": True, "session_id": session_id, "directory": directory}
    return None
