"""Per-turn user prompts for one Claude Code session (job detail view).

Served lazily, one session at a time, straight from the session's transcript at
``<config>/projects/<encoded-cwd>/<id>.jsonl``. Only top-level user prompts are
returned: tool results, sidechain (sub-agent) records, meta records, and injected
tag blocks (``<system-reminder>``, ``<command-name>``, ...) are filtered out.

In HEARTH the "user" is the harness: the task message, ``finish`` rejections fed
back as fix-ups, and ``/hearth revise`` instructions. Seeing them turn by turn is
what a reviewer needs to follow why the agent changed what it changed.

``session_id`` may be a HEARTH job id (resolved through the session index), a
native Claude session id, or ``claude_code:<native id>``.

Shape mirrors xo-space ``adapters/claude_code/session_prompts.py``.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from services.hearth_agent.adapters.claude_code._project_encoding import projects_dir
from services.hearth_agent.engine import sessions_io as _session_index

SOURCE_ID = "claude_code"
SOURCE_LABEL = "Claude Code"

MAX_PROMPTS = 200          # newest prompts kept; the detail card stays bounded
MAX_PROMPT_CHARS = 4000    # per-prompt cap; the card is a summary, not a transcript browser
_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

_TAG_BLOCK_RE = re.compile(
    r"<(system-reminder|local-command-stdout|local-command-stderr)>.*?</\1>",
    re.DOTALL,
)
_COMMAND_NAME_RE = re.compile(r"<command-name>(.*?)</command-name>", re.DOTALL)
_COMMAND_ARGS_RE = re.compile(r"<command-args>(.*?)</command-args>", re.DOTALL)


def _projects_dir() -> Path:
    return projects_dir()


def _native_session_id(session_id: str) -> str:
    """Accept ``claude_code:<native>``, a native id, or a HEARTH job id from the index."""
    native = session_id.split(":", 1)[1] if session_id.startswith(f"{SOURCE_ID}:") else session_id
    row = _session_index.read_session_row(native) if _SESSION_ID_RE.fullmatch(native) else None
    if row and row.get("nativeSessionId"):
        native = row["nativeSessionId"]
    if not _SESSION_ID_RE.fullmatch(native):
        raise ValueError(f"invalid session id: {session_id!r}")
    return native


def _find_transcript(native_id: str) -> Path:
    """Locate ``<native_id>.jsonl`` under any encoded project directory (newest wins)."""
    root = _projects_dir()
    if not root.is_dir():
        raise FileNotFoundError(f"Claude Code projects directory not found at {root}")
    matches = [c for e in root.iterdir() if e.is_dir() and (c := e / f"{native_id}.jsonl").is_file()]
    if not matches:
        raise FileNotFoundError(f"No transcript found for session {native_id!r} under {root}")
    return max(matches, key=lambda path: path.stat().st_mtime_ns)


def _clean_text(raw: str) -> str | None:
    """Reduce one text payload to the human/harness-typed part, or None."""
    text = _TAG_BLOCK_RE.sub("", raw)
    command = _COMMAND_NAME_RE.search(text)
    if command:
        name = command.group(1).strip()
        args_match = _COMMAND_ARGS_RE.search(text)
        args = args_match.group(1).strip() if args_match else ""
        combined = (name + (" " + args if args else "")).strip()
        return combined or None
    text = text.strip()
    if not text or text.startswith("<") or text.startswith("[Request interrupted"):
        return None
    return text


def _prompt_text(record: dict) -> str | None:
    """Typed prompt text from one ``type: "user"`` record, or None (sidechain, meta, tool_result-only)."""
    if record.get("isMeta") or record.get("isSidechain"):
        return None
    message = record.get("message")
    if not isinstance(message, dict):
        return None
    content = message.get("content")
    if isinstance(content, str):
        return _clean_text(content)
    if isinstance(content, list):
        parts = [
            cleaned
            for item in content
            if isinstance(item, dict) and item.get("type") == "text"
            and isinstance(item.get("text"), str)
            and (cleaned := _clean_text(item["text"]))
        ]
        return "\n".join(parts) or None
    return None


def collect_session_prompts(session_id: str) -> dict:
    """One entry per exchange: a turn starts at a typed prompt and owns every
    assistant reply and tool call until the next typed prompt."""
    native_id = _native_session_id(session_id)
    transcript = _find_transcript(native_id)

    prompts: list[dict] = []
    with transcript.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue  # an active session can end mid-line
            if not isinstance(record, dict):
                continue
            kind = record.get("type")
            if kind == "assistant":
                if record.get("isSidechain") or not prompts:
                    continue
                current = prompts[-1]
                current["responses"] += 1
                message = record.get("message")
                content = message.get("content") if isinstance(message, dict) else None
                if isinstance(content, list):
                    current["tool_uses"] += sum(
                        1 for item in content if isinstance(item, dict) and item.get("type") == "tool_use"
                    )
                continue
            if kind != "user":
                continue
            text = _prompt_text(record)
            if text is None:
                continue
            prompts.append({
                "timestamp": record.get("timestamp"),
                "text": text[:MAX_PROMPT_CHARS],
                "truncated": len(text) > MAX_PROMPT_CHARS,
                "responses": 0,
                "tool_uses": 0,
            })

    total = len(prompts)
    prompts = prompts[-MAX_PROMPTS:]
    for turn, prompt in enumerate(prompts, start=total - len(prompts) + 1):
        prompt["turn"] = turn
    return {
        "source": {"id": SOURCE_ID, "label": SOURCE_LABEL},
        "session_id": session_id,
        "supported": True,
        "total_prompts": total,
        "capped": total > len(prompts),
        "prompts": prompts,
    }
