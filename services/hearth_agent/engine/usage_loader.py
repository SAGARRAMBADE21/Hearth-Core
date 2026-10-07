"""Thin alias resolving the active agent's ``usage`` capability.

Shape mirrors xo-space ``engine/usage_loader.py``.
"""

from __future__ import annotations

from types import ModuleType

from services.hearth_agent.adapters.loader import load_capability


def load_usage_module() -> ModuleType:
    return load_capability("usage")
