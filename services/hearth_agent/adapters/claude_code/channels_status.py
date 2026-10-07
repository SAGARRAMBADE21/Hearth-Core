"""
Claude Code channels-status view.

claude_code has ``channels.enabled = false`` in capabilities.json (HEARTH sends
Slack/email notifications from the backend, not through the agent). It has no
channel sources to query, so this adapter returns the empty envelope so the
``/channels/status`` route treats claude_code uniformly.

``ClaudeCodeStatusError`` is re-exported for symmetry with models_status; the
router catches it.

Shape mirrors xo-space ``adapters/claude_code/channels_status.py``.
"""

from __future__ import annotations

from typing import Any

from services.hearth_agent.adapters.claude_code.models_status import ClaudeCodeStatusError

_EMPTY_VIEW: dict[str, Any] = {"channels": []}


def build_status_view(_: Any = None) -> dict[str, Any]:
    """Return the empty channels envelope. Argument ignored; keeps the
    ``build_status_view(parsed_payload)`` signature the other views use."""
    return dict(_EMPTY_VIEW)


async def get_channels_status(timeout: float | None = None) -> dict[str, Any]:
    """No CLI call needed — claude_code has no channels."""
    return build_status_view()


__all__ = ["ClaudeCodeStatusError", "build_status_view", "get_channels_status"]
