"""Read-only session telemetry for the Claude Code runtime — not supported in HEARTH.

xo-space feeds this capability from Argus (a local ingestion daemon and SQLite
database). HEARTH does not ship Argus: per-job usage comes from the SDK's final
result (``engine/sessions_io`` rows, served by ``usage.py``), and traces go
through OpenTelemetry inside the space (TDD §10). The contract stays so a
telemetry route can ask every runtime the same question and get a clear
"unsupported" answer instead of an import error.

Shape mirrors xo-space ``adapters/claude_code/session_telemetry.py``.
"""

from __future__ import annotations

SOURCE_ID = "claude_code"
SOURCE_LABEL = "Claude Code"
META_PRIORITY = 100
COST_STATUS = "unsupported"
SUPPORTED = False
REASON = "HEARTH records per-job usage in the session index (see /api/usage) and traces with OpenTelemetry; no Argus."

SOURCE_CONFIG = {
    "vendor": "anthropic",
    "path_env": None,
    "path_default": None,
    "path_kind": None,
    "path_label": None,
    "collects": [],
    "never": "No prompt text stored",
}


def collect_session_telemetry() -> dict:
    return {
        "source": {"id": SOURCE_ID, "label": SOURCE_LABEL, "cost_status": COST_STATUS},
        "supported": SUPPORTED,
        "reason": REASON,
        "meta_priority": META_PRIORITY,
        "meta": {},
        "totals": {},
        "project_keys": [],
        "sessions": [],
        "daily_models": [],
        "daily_sessions": [],
        "daily_tools": [],
    }


def start_daemon() -> None:
    """No daemon to start in HEARTH."""


def stop_daemon() -> None:
    """No daemon to stop in HEARTH."""
