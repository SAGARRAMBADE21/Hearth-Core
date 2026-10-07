"""
Dynamic capability resolver — the single seam every agent-specific module is
reached through.

Everything agent-specific lives at ``services.hearth_agent.adapters.<AGENT_NAME>.<capability>``
and is resolved from the active agent (``AGENT_NAME`` → ``DEFAULT_AGENT`` →
single-manifest auto-pick, via ``get_active_agent()``). No core module names a
specific agent; it asks for a *capability* and the loader imports the active
agent's implementation.

Capabilities are module names inside the adapter package, e.g. ``adapter``,
``streaming``, ``mcp_tools``, ``hooks``, ``routes``.

Shape mirrors xo-space ``adapters/loader.py``.
"""

from __future__ import annotations

import importlib
from pathlib import Path
from types import ModuleType

import services.hearth_agent.adapters as _adapters_pkg
from services.hearth_agent.registry.agent_registry import get_active_agent

_ADAPTERS_DIR = Path(_adapters_pkg.__file__).resolve().parent


def _module_name(capability: str, agent: str) -> str:
    if not capability.isidentifier():
        raise ValueError(f"invalid capability name: {capability!r}")
    if not agent.isidentifier():
        raise ValueError(f"invalid agent name: {agent!r}")
    return f"services.hearth_agent.adapters.{agent}.{capability}"


def load_capability(capability: str, *, agent: str | None = None) -> ModuleType:
    """Import the (active) agent's implementation of ``capability``.

    Raises ModuleNotFoundError naming the import path when the agent lacks it.
    """
    name = agent or get_active_agent().name
    return importlib.import_module(_module_name(capability, name))


def try_load_capability(capability: str, *, agent: str | None = None) -> ModuleType | None:
    """Like :func:`load_capability` but returns ``None`` when the agent does not implement ``capability``.

    A missing dependency *inside* a capability that exists is re-raised, so a broken
    install is never disguised as "unsupported".
    """
    name = agent or get_active_agent().name
    expected = _module_name(capability, name)
    provider_package = expected.rsplit(".", 1)[0]
    try:
        return importlib.import_module(expected)
    except ModuleNotFoundError as exc:
        if exc.name not in {expected, provider_package}:
            raise
        return None


def list_capability_providers(capability: str) -> list[str]:
    """Return every adapter package that implements ``capability``."""
    if not capability.isidentifier():
        raise ValueError(f"invalid capability name: {capability!r}")
    if not _ADAPTERS_DIR.is_dir():
        return []
    return sorted(
        entry.name
        for entry in _ADAPTERS_DIR.iterdir()
        if entry.is_dir() and entry.name.isidentifier() and (entry / f"{capability}.py").is_file()
    )
