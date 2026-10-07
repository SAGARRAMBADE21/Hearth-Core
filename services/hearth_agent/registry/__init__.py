"""
The agent framework: discovery, configuration, and dispatch wiring.

- agent_registry   : discover config/agents/<name>/manifest.json, resolve the
                     active agent by AGENT_NAME / DEFAULT_AGENT
- adapter_registry : instantiate the active agent's adapter (auto-discovered)
- settings         : agent-agnostic env/config, settings.json + capabilities.json loaders

This is the seam every agent plugs into; it names no specific agent itself.
"""
