"""
Claude Code usage — discovery + parser + aggregates (PRD §5: cost per run, monthly budget).

Loaded by ``services.hearth_agent.engine.usage_loader.load_usage_module()`` when
``AGENT_NAME=claude_code``.

Sources, in order of authority:
  * the session index (``engine/sessions_io``): per job, the SDK's own final
    ``usage``, ``costUsd`` and ``numTurns`` — the billed numbers;
  * the job's transcript (``<config>/projects/<encoded>/<native>.jsonl``): per
    assistant turn, tokens and model, for the per-day / per-model breakdown.
    Records are deduped by ``message.id`` (every streaming chunk shares one id).

Unlike xo-space (which walks every transcript on the machine, as ``claude /usage``
does), discovery is limited to sessions HEARTH ran: a space runs nothing else.

Public contract kept from xo-space ``adapters/claude_code/usage.py``:
``get_session_files``, ``parse_file``, ``dashboard``, ``build_summary``,
``analytics``, ``summary``, ``summary_card``, ``list_sessions``, ``get_session``,
``aggregate_for_sync`` / ``sync_payload``. ``window`` is ``{"days": N}`` or
``{"start_ms": .., "end_ms": ..}``.
"""

from __future__ import annotations

import json
import os
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

from services.hearth_agent.adapters.claude_code.sessions import resolve_native_file
from services.hearth_agent.engine import sessions_io as _session_index

_TOKEN_KEYS = ("input", "output", "cacheRead", "cacheWrite")


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _record_time(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def _read_jsonl(path: str | Path) -> list[dict]:
    out: list[dict] = []
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(rec, dict):
                    out.append(rec)
    except OSError:
        return []
    return out


def _date(ms: int | None) -> str | None:
    return datetime.fromtimestamp(ms / 1000, UTC).date().isoformat() if ms else None


def _window_to_ms(window: dict | None) -> tuple[int | None, int | None]:
    window = window or {}
    if "days" in window:
        days = max(1, min(int(window["days"]), 366))
        start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=days - 1)
        return int(start.timestamp() * 1000), None
    return window.get("start_ms"), window.get("end_ms")


def _empty_tokens() -> dict[str, int]:
    return {k: 0 for k in (*_TOKEN_KEYS, "totalTokens")}


# ─────────────────────────────────────────────────────────────────────────────
# Discovery + parser
# ─────────────────────────────────────────────────────────────────────────────

def get_session_files(*, agent_id: str | None = None) -> list[str]:
    """Transcript paths for indexed sessions (``agent_id`` filters to one job)."""
    files: list[str] = []
    for key, row in _session_index.iter_session_rows():
        if agent_id and key != agent_id:
            continue
        path = resolve_native_file(row, key)
        if path is not None:
            files.append(str(path))
    return files


def parse_file(path: str, *, start_ms: int | None = None, end_ms: int | None = None) -> tuple[dict, list]:
    """Parse one transcript into ``(meta, entries)`` with xo-space's normalized entry shape."""
    meta: dict = {"sessionId": None, "sessionFile": os.path.basename(path)}
    entries: list = []
    seen_message_ids: set[str] = set()
    last_user_ts: int | None = None
    base = os.path.basename(path)
    if base.endswith(".jsonl"):
        meta["sessionId"] = base[: -len(".jsonl")]

    for record in _read_jsonl(path):
        msg = record.get("message") or {}
        rt = _record_time(record.get("timestamp"))
        ts = int(rt.timestamp() * 1000) if rt else None
        if ts is not None and ((start_ms and ts < start_ms) or (end_ms and ts > end_ms)):
            continue
        sid = record.get("sessionId")
        if isinstance(sid, str) and sid:
            meta["sessionId"] = sid

        if record.get("type") == "user":
            content = msg.get("content", "")
            has_text = (isinstance(content, str) and content.strip()) or (
                isinstance(content, list) and any(isinstance(b, dict) and b.get("type") == "text" for b in content)
            )
            if has_text:  # pure tool_result records are protocol noise, not turns
                last_user_ts = ts
                entries.append({"role": "user", "timestamp": ts})
            continue
        if record.get("type") != "assistant":
            continue
        usage = msg.get("usage") or {}
        if not usage:
            continue
        msg_id = msg.get("id")
        if isinstance(msg_id, str) and msg_id:
            if msg_id in seen_message_ids:
                continue
            seen_message_ids.add(msg_id)
        inp = int(usage.get("input_tokens", 0) or 0)
        out = int(usage.get("output_tokens", 0) or 0)
        cache_r = int(usage.get("cache_read_input_tokens", 0) or 0)
        cache_w = int(usage.get("cache_creation_input_tokens", 0) or 0)
        content = msg.get("content") if isinstance(msg.get("content"), list) else []
        entries.append({
            "role": "assistant",
            "usage": {"input": inp, "output": out, "cacheRead": cache_r, "cacheWrite": cache_w,
                      "totalTokens": inp + out + cache_r + cache_w},
            "provider": "anthropic",
            "model": msg.get("model") or "claude",
            "timestamp": ts,
            "stopReason": msg.get("stop_reason"),
            "toolNames": [b.get("name") for b in content if isinstance(b, dict) and b.get("type") == "tool_use"],
            "durationMs": (ts - last_user_ts) if (ts and last_user_ts) else None,
        })
    return meta, entries


# ─────────────────────────────────────────────────────────────────────────────
# Aggregates
# ─────────────────────────────────────────────────────────────────────────────

def build_summary(session_meta: dict, entries: list) -> dict:
    """Aggregate one session's entries: tokens, per-day and per-model totals, tools, latency."""
    tokens = _empty_tokens()
    by_day: dict[str, dict] = defaultdict(lambda: {"date": "", "tokens": 0, "messages": 0})
    by_model: dict[str, dict] = defaultdict(lambda: {"model": "", "tokens": 0, "count": 0})
    tools: dict[str, int] = defaultdict(int)
    latencies = [e["durationMs"] for e in entries if e.get("durationMs")]
    users = assistants = 0
    first = last = None
    for e in entries:
        ts = e.get("timestamp")
        if ts:
            first = ts if first is None else min(first, ts)
            last = ts if last is None else max(last, ts)
        if e["role"] == "user":
            users += 1
            continue
        assistants += 1
        u = e["usage"]
        for k in (*_TOKEN_KEYS, "totalTokens"):
            tokens[k] += u.get(k, 0)
        day = _date(ts)
        if day:
            by_day[day].update(date=day)
            by_day[day]["tokens"] += u["totalTokens"]
            by_day[day]["messages"] += 1
        m = by_model[e["model"]]
        m.update(model=e["model"])
        m["tokens"] += u["totalTokens"]
        m["count"] += 1
        for name in e.get("toolNames") or []:
            tools[name] += 1
    return {
        "sessionId": session_meta.get("sessionId"),
        "jobId": session_meta.get("jobId"),
        "tokens": tokens,
        "costUsd": session_meta.get("costUsd"),
        "numTurns": session_meta.get("numTurns"),
        "messages": {"total": users + assistants, "user": users, "assistant": assistants},
        "firstActivity": first,
        "lastActivity": last,
        "avgLatencyMs": round(sum(latencies) / len(latencies)) if latencies else None,
        "dailyUsage": sorted(by_day.values(), key=lambda d: d["date"]),
        "modelUsage": sorted(by_model.values(), key=lambda m: -m["tokens"]),
        "tools": dict(sorted(tools.items(), key=lambda kv: -kv[1])),
    }


def _sessions_in_window(window: dict | None) -> list[tuple[str, dict, dict]]:
    """``(key, row, summary)`` for every indexed session active in the window."""
    start_ms, end_ms = _window_to_ms(window)
    out = []
    for key, row in _session_index.iter_session_rows():
        updated = row.get("updatedAt") or 0
        if start_ms and updated and updated < start_ms:
            continue
        path = resolve_native_file(row, key)
        entries = parse_file(str(path), start_ms=start_ms, end_ms=end_ms)[1] if path else []
        meta = {"sessionId": key, "jobId": row.get("jobId", key), "costUsd": row.get("costUsd"),
                "numTurns": row.get("numTurns")}
        out.append((key, row, build_summary(meta, entries)))
    return out


def _row_tokens(row: dict) -> dict[str, int]:
    u = row.get("usage") or {}
    t = {"input": u.get("input_tokens", 0), "output": u.get("output_tokens", 0),
         "cacheRead": u.get("cache_read_input_tokens", 0), "cacheWrite": u.get("cache_creation_input_tokens", 0)}
    t["totalTokens"] = sum(t.values())
    return t


def dashboard(*, window: dict) -> dict:
    """The ``/api/usage`` payload: totals from the SDK's own per-job numbers, breakdowns from transcripts."""
    sessions = _sessions_in_window(window)
    totals = _empty_tokens()
    total_cost = 0.0
    by_day: dict[str, dict] = defaultdict(lambda: {"date": "", "tokens": 0, "cost": 0.0, "sessions": 0})
    by_model: dict[str, dict] = defaultdict(lambda: {"model": "", "tokens": 0, "count": 0})
    for _key, row, summary_ in sessions:
        row_tokens = _row_tokens(row)
        for k in totals:
            totals[k] += row_tokens[k] or summary_["tokens"][k]
        cost = float(row.get("costUsd") or 0.0)
        total_cost += cost
        day = _date(row.get("updatedAt"))
        if day:
            by_day[day].update(date=day)
            by_day[day]["tokens"] += row_tokens["totalTokens"] or summary_["tokens"]["totalTokens"]
            by_day[day]["cost"] += cost
            by_day[day]["sessions"] += 1
        for m in summary_["modelUsage"]:
            agg = by_model[m["model"]]
            agg.update(model=m["model"])
            agg["tokens"] += m["tokens"]
            agg["count"] += m["count"]
    return {
        "total_sessions": len(sessions),
        "total_tokens": totals,
        "total_cost": round(total_cost, 6),
        "by_day": sorted(by_day.values(), key=lambda d: d["date"]),
        "by_model": sorted(by_model.values(), key=lambda m: -m["tokens"]),
        "top_sessions": sorted(
            ({"session_id": k, "job_id": r.get("jobId", k), "status": r.get("status"),
              "cost": r.get("costUsd"), "tokens": _row_tokens(r)["totalTokens"]} for k, r, _ in sessions),
            key=lambda s: -(s["cost"] or 0),
        )[:10],
    }


def analytics(*, window: dict) -> dict:
    d = dashboard(window=window)
    return {"by_day": d["by_day"], "by_model": d["by_model"]}


def summary(*, window: dict) -> dict:
    d = dashboard(window=window)
    return {"total_sessions": d["total_sessions"], "total_tokens": d["total_tokens"], "total_cost": d["total_cost"]}


def summary_card(*, window: dict) -> dict:
    s = summary(window=window)
    return {"sessions": s["total_sessions"], "tokens": s["total_tokens"]["totalTokens"], "cost": s["total_cost"]}


def list_sessions() -> dict:
    return {"sessions": [
        {"session_id": k, "job_id": r.get("jobId", k), "native_session_id": r.get("nativeSessionId"),
         "status": r.get("status"), "model": r.get("model"), "cost": r.get("costUsd"),
         "tokens": _row_tokens(r), "updated_at": r.get("updatedAt")}
        for k, r in _session_index.iter_session_rows()
    ]}


def get_session(session_id: str, *, window: dict | None = None) -> dict | None:
    row = _session_index.read_session_row(session_id)
    if row is None:
        return None
    start_ms, end_ms = _window_to_ms(window)
    path = resolve_native_file(row, session_id)
    entries = parse_file(str(path), start_ms=start_ms, end_ms=end_ms)[1] if path else []
    return build_summary({"sessionId": session_id, "jobId": row.get("jobId", session_id),
                          "costUsd": row.get("costUsd"), "numTurns": row.get("numTurns")}, entries)


def aggregate_for_sync(*, since_date: str | None = None) -> dict:
    """Per-day totals with no identifiers — the only shape usage may take outside the
    space, and only when the customer opts in to telemetry (PRD §4)."""
    days: dict[str, dict] = defaultdict(lambda: {"date": "", "sessions": 0, "tokens": 0, "cost": 0.0})
    for _key, row in _session_index.iter_session_rows():
        day = _date(row.get("updatedAt"))
        if not day or (since_date and day < since_date):
            continue
        d = days[day]
        d["date"] = day
        d["sessions"] += 1
        d["tokens"] += _row_tokens(row)["totalTokens"]
        d["cost"] += float(row.get("costUsd") or 0.0)
    return {"days": sorted(days.values(), key=lambda d: d["date"])}


# Canonical sync surface name, as in xo-space.
sync_payload = aggregate_for_sync

__all__: list[str] = [
    "aggregate_for_sync", "analytics", "build_summary", "dashboard", "get_session", "get_session_files",
    "list_sessions", "parse_file", "summary", "summary_card", "sync_payload",
]
