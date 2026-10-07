"""
Claude-code providers-status adapter.

The Anthropic key, the LLM gateway, and the Claude subscription login are
*mutually exclusive* ways the CLI can be authenticated, and it only ever resolves
to one at a time. Rather than checking each independently (which lights several
tiles when a variable is merely present), we run ``claude auth status`` **once**
and route by what the CLI actually resolved to:

- ``ANTHROPIC_BASE_URL`` set in the jobs' env (the space's LLM gateway or another
  Anthropic-compatible gateway) and logged in → the **LLM gateway** tile.
- ``apiKeySource == "ANTHROPIC_API_KEY"`` (bring your own key) → the Anthropic
  **API key** tile.
- logged in by any other method (claude.ai login, OAuth token) → the **Claude
  Code** OAuth tile.

The probe runs with the **same environment the jobs use** (``Adapter.cli_env()``),
so the tiles reflect what a job will actually resolve to. This stays
presence-not-validity: a logged-in-but-invalid credential still reads connected.

Shape mirrors xo-space ``adapters/claude_code/providers_status.py``; OpenRouter /
OpenAI are replaced by HEARTH's LLM gateway.
"""

from __future__ import annotations

import os
from typing import Any

from services.hearth_agent.adapters.claude_code.adapter import ClaudeCodeAdapter
from services.hearth_agent.providers_status_lib import build_providers_status, claude_auth_status


def _gateway_configured(env: dict[str, str]) -> bool:
    merged = {**os.environ, **env}
    return bool((merged.get("ANTHROPIC_BASE_URL") or "").strip())


async def get_providers_status() -> dict[str, Any]:
    env = ClaudeCodeAdapter({}).cli_env()
    auth = await claude_auth_status(env=env)
    logged_in = bool(auth.get("loggedIn"))
    via_gateway = logged_in and _gateway_configured(env)
    via_api_key = logged_in and not via_gateway and (auth.get("apiKeySource") or "") == "ANTHROPIC_API_KEY"

    return await build_providers_status(
        "claude_code",
        anthropic_key_present=lambda: via_api_key,
        llm_gateway_present=lambda: via_gateway,
        claude_oauth_present=lambda: logged_in and not via_api_key and not via_gateway,
    )


__all__ = ["get_providers_status"]
