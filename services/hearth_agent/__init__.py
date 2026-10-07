"""
hearth_agent — HEARTH's agent subsystem (mirrors xo-space's ``services/cowork_agent``).

- adapters/    one package per coding intelligence (``claude_code``), discovered by convention
- connectors/  external services (``github``) and the shared ``token_store``
- engine/      dispatcher + the stream event vocabulary
- registry/    manifest discovery (``config/agents/<name>/``), adapter resolution, settings
- models.py    records shared across HEARTH (Change Record, Impact Report, JobSpec, AgentResult)
- policy.py    the tool-layer policy every adapter enforces
"""
