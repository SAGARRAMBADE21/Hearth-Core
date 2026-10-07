from __future__ import annotations

import json
from typing import Any

from claude_agent_sdk import (
    AssistantMessage,
    ResultMessage,
    SystemMessage,
    TextBlock,
    ThinkingBlock,
    ToolUseBlock,
)

from services.hearth_agent.engine import stream_events as se


def parse_message(msg: Any) -> list[dict]:
    """
    Turn one Claude Agent SDK message into normalised events (see ``engine.stream_events``).

    The counterpart of xo-space's ``parse_stream_line``: xo-space decodes the CLI's
    ``stream-json`` lines itself, while HEARTH receives the same messages already
    typed by the SDK. Thinking text never leaves here (it becomes a label); tool
    inputs do, as audit events, because every agent action must be on the record.
    """
    if isinstance(msg, SystemMessage):
        if msg.subtype == "init":
            sid = (msg.data or {}).get("session_id")
            return [se.session_id(sid)] if sid else []
        return []

    if isinstance(msg, AssistantMessage):
        events: list[dict] = []
        for block in msg.content:
            if isinstance(block, TextBlock):
                if block.text:
                    events.append(se.token(block.text))
            elif isinstance(block, ThinkingBlock):
                events.append(se.activity(se.THINKING))
            elif isinstance(block, ToolUseBlock):
                events.append(se.running(block.name))
                events.append(se.tool_call(block.name, block.id, dict(block.input or {})))
        if msg.error:
            events.append(se.error(str(msg.error)))
        return events

    if isinstance(msg, ResultMessage):
        payload = se.result(
            result=msg.result or "",
            session_id=msg.session_id,
            usage=msg.usage or {},
            total_cost_usd=msg.total_cost_usd,
            num_turns=msg.num_turns,
            stop_reason=msg.stop_reason,
        )
        if msg.is_error:
            return [se.error(msg.result or f"Claude Code error ({msg.subtype})"), payload]
        return [payload]

    # UserMessage (tool results going back to the agent; captured by the PostToolUse
    # hook instead), rate-limit and stream events: not part of the record here.
    return []


def trim_output(value: Any, limit: int = 4000) -> str:
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    return text if len(text) <= limit else text[:limit] + f"... [{len(text) - limit} chars trimmed]"
