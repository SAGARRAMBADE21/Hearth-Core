"""The session index: one row per agent session, keyed by HEARTH job id.

Shape mirrors xo-space ``engine/sessions_io.py`` (a partitioned index, one shard
file per row so concurrent writers never rewrite each other's rows), stored under
the state root instead of a project folder:

    $HEARTH_STATE_DIR/sessions/sessionslist.d/<key>.json

Row fields (camelCase, as in xo-space)::

    sessionId          HEARTH's id for the session (the job id)
    jobId              the job this session ran
    nativeSessionId    Claude Code's own session id (its transcript file name)
    directory          the sandbox workspace the CLI ran in (its cwd)
    directoryHistory   [{directory, selectedAt}]
    backend            "claude_code"
    model              the model the job used
    resumedFrom        job id whose session this one forked from (``/hearth revise``), or null
    status             the job's AgentResult status once known
    createdAt / updatedAt   epoch milliseconds
    usage              {input_tokens, output_tokens, cache_creation_input_tokens, cache_read_input_tokens}
    costUsd, numTurns  from the SDK's final result
"""

from __future__ import annotations

import json
import os
import re
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from services.storage.paths import hearth_state_dir

_KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")


def empty_usage() -> dict[str, int]:
    return {"input_tokens": 0, "output_tokens": 0, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}


def now_ms() -> int:
    return int(time.time() * 1000)


def index_dir() -> Path:
    return hearth_state_dir() / "sessions" / "sessionslist.d"


def _shard(key: str) -> Path:
    if not _KEY_RE.fullmatch(key):
        raise ValueError(f"invalid session key: {key!r}")
    return index_dir() / (key.replace(":", "__") + ".json")


def read_session_row(key: str) -> dict[str, Any] | None:
    try:
        data = json.loads(_shard(key).read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError, OSError):
        return None
    return data if isinstance(data, dict) else None


def write_session_row(key: str, row: dict[str, Any]) -> bool:
    """Publish one row atomically (temp file + rename). Returns False on an I/O failure."""
    path = _shard(key)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(row, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        return False
    return True


def delete_session_row(key: str) -> bool:
    try:
        _shard(key).unlink()
    except FileNotFoundError:
        return False
    return True


def iter_session_rows() -> Iterator[tuple[str, dict[str, Any]]]:
    """Every ``(key, row)`` in the index, newest first."""
    d = index_dir()
    if not d.is_dir():
        return
    rows: list[tuple[str, dict[str, Any]]] = []
    for f in d.glob("*.json"):
        try:
            row = json.loads(f.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue
        if isinstance(row, dict):
            rows.append((f.stem.replace("__", ":"), row))
    rows.sort(key=lambda kv: kv[1].get("updatedAt") or 0, reverse=True)
    yield from rows


def read_session_index() -> dict[str, dict[str, Any]]:
    """Merged ``{key: row}`` for the whole index."""
    return dict(iter_session_rows())
