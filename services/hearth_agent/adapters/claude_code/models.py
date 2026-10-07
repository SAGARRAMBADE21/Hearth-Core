"""
claude_code model listing (`/api/models`).

xo-space's claude_code re-exports openclaw's listing (one row per openclaw agent
folder). HEARTH has no openclaw, so the rows come from the manifest instead: the
default model plus ``model.allowed`` — the models a job (``JobSpec.model``) or
``HEARTH_MODEL`` may select. The row shape is the one openclaw's ``list_models``
returns, so the UI reads both the same way.
"""

from __future__ import annotations

from services.hearth_agent.registry.agent_registry import get_agent


def list_models() -> list[dict]:
    """One row per selectable model, the default first, as ``<prefix>/<model>``."""
    agent = get_agent("claude_code")
    model_cfg = agent.raw.get("model") or {}
    ids: list[str] = []
    for model in [agent.model_default, *(model_cfg.get("allowed") or [])]:
        if model and model not in ids:
            ids.append(model)
    return [
        {
            "id": f"{agent.model_prefix}/{model}",
            "name": model,
            "provider_id": agent.name,
            "capabilities": dict(agent.model_capabilities),
            "pricing": {"prompt": 0, "completion": 0},  # billed by the customer's own key or gateway
            "metadata": {"model": model, "default": model == agent.model_default,
                         "effort": model_cfg.get("effort")},
        }
        for model in ids
    ]


__all__ = ["list_models"]
