"""
Environment and adapter config for the hearth_agent subsystem.

Holds only agent-agnostic config. Each backend's own constants live in its
manifest (``config/agents/<name>/manifest.json``) and its adapter package.

Shape mirrors xo-space ``registry/settings.py``.
"""

import json
import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env so consumers see configured values at import time.
load_dotenv()

_REPO_ROOT = Path(__file__).resolve().parents[3]


def load_agent_config(agent_name: str) -> dict:
    """
    Load ``config/agents/{agent_name}/settings.json`` and resolve ``*_env`` keys.

    For every key ending in ``_env``, reads ``os.environ.get(value)`` and adds the
    resolved value under the key with ``_env`` stripped.

    Example: ``"cli_path_env": "CLAUDE_CLI_PATH"`` → also sets ``"cli_path": <env value>``.
    Raises FileNotFoundError if the settings file is absent.
    """
    settings_path = _REPO_ROOT / "config" / "agents" / agent_name / "settings.json"
    if not settings_path.exists():
        raise FileNotFoundError(
            f"No settings file for agent '{agent_name}': expected {settings_path}. "
            f"Create config/agents/{agent_name}/settings.json."
        )
    config: dict = json.loads(settings_path.read_text(encoding="utf-8"))
    resolved: dict = {}
    for key, value in config.items():
        if key.endswith("_env") and isinstance(value, str):
            resolved[key[: -len("_env")]] = os.environ.get(value)
    config.update(resolved)
    return config


def load_agent_capabilities(agent_name: str) -> dict:
    """``config/agents/{agent_name}/capabilities.json``, or ``{}`` when absent."""
    path = _REPO_ROOT / "config" / "agents" / agent_name / "capabilities.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
