# Hearth-Core - Project Memory

## Project overview

- FastAPI service that runs inside each HEARTH space (one Docker container on the customer's machine).
- Holds three things: the GitHub connector (gh CLI), the API diff engine, and the Claude Code adapter.
- Hearth-backend's engine services (Engine API, Orchestrator, Sandbox Runner, PR Service) import these
  modules and call this API. Product docs: `../HEARTH_PRD.pdf`, `../HEARTH_TDD.pdf`.
- Claude Code is the only intelligence. There is no OpenCode fork; do not add one.

## Architecture conventions

- Layout mirrors xo-space (`../xo-space`, reference only — never copy it wholesale):
  `routers/hearth_agent/` (thin APIRouters) → `services/hearth_agent/` (agent-specific logic) and
  top-level `services/<name>/` for shared space-level pieces (`services/storage/`).
- The API diff engine is its own root-level package, `apidiff/` (`from apidiff import ...`), not under
  `services/`. CLI: `python -m apidiff.cli OLD NEW`.
- Keep route handlers thin; logic lives in services.
- Every external command runs through `utils/commands` (`run` over an argv list, `safe_arg` for untrusted
  values). No `shell=True`, no command strings.

## Agent-modular architecture

- Core never names a specific agent. The active agent comes from `config/agents/<name>/manifest.json`
  via `services/hearth_agent/registry/agent_registry.py` (`AGENT_NAME` → `DEFAULT_AGENT` → sole manifest).
- Agent-specific code lives only in `config/agents/<name>/` and `services/hearth_agent/adapters/<name>/`.
  `adapters/loader.py` (`load_capability` / `try_load_capability`) is the one seam to reach it.
- Every adapter's `stream()` speaks `services/hearth_agent/engine/stream_events.py` and ends with exactly
  one `{"done": True, "native_session_id", "result"}`.

## Security invariants (from the TDD — do not weaken)

- Claude Code never runs with permissions bypassed. `manifest.json` `flags.dangerously_skip_permissions`
  must stay `false`; the adapter refuses to start otherwise.
- The tool-layer policy (`services/hearth_agent/policy.py`) is enforced in the `PreToolUse` hook for every
  tool call. Edits outside the Impact Report scope, CI config, secrets and `.git/` are denied; network
  tools, `git push/remote/fetch`, `gh`, `sudo` are denied.
- `finish` is accepted only after `HarnessHooks.validate_candidate()` passes.
- Remote Control (`adapters/claude_code/remote_control.py`) stays off unless an operator sets
  `remote_control.enabled: true` in `config/agents/claude_code/capabilities.json`: it lets claude.ai drive a
  Claude Code session in the space outside the sandbox and policy. `start()` refuses (route: 403) otherwise.
- The adapter package mirrors xo-space's `claude_code/` module for module. Modules that do not fit HEARTH
  (`session_telemetry`, `visualizer_source`) keep the contract and report `supported: False`; `agents` serves
  the one built-in migrator and answers 405 to create/patch/delete.
- The GitHub token lives only in gh's store (`gh auth login --with-token`). `token.json` holds metadata.
  Never write a token into a remote URL, a sandbox, a log, an error message, or a JSON file. Every gh call
  runs without `GH_TOKEN`/`GITHUB_TOKEN` (`gh_api.STORE_BYPASS_ENV`), so gh's store is the only credential.
- One gh account per space: connecting signs gh out of every other github.com account; disconnecting signs
  it out of all of them and removes the git identity and credential helper connecting wrote
  (quirq-ai/xo-space#197).
- Sandboxes receive `RepoMirror.export_tree()` output: no `.git` remote, no credential.

## Testing

- `python -m unittest discover -s tests -t .` is the gate; `python -m pytest -q` also works.
- Tests are plain `unittest.TestCase` / `IsolatedAsyncioTestCase`. No test calls a model or GitHub.
