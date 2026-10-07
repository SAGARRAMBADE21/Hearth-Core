# Hearth-Core - Agent Instructions

Read `CLAUDE.md` first; it is the project memory and applies to every coding agent working here.

## Quick reference

- Install and run: `./install.sh` (add `--dev` for test tools, `--no-start` to only install);
  `./hearth-core.sh dev` runs with auto-reload.
- Test: `./hearth-core.sh test` (or `python -m unittest discover -s tests -t .`).
- Add a route: a module under `routers/hearth_agent/` exposing `router`, listed in
  `routers/hearth_agent/__init__.py` `all_routers`.
- Add a GitHub capability: a module under `services/hearth_agent/connectors/github/`, re-exported from its
  `__init__.py`. Use `GhCli` (classified `GhResult`s); never shell out to `gh` directly.
- Change agent behaviour: prefer `config/agents/claude_code/manifest.json` (`model`, `flags`, `mcp`) over code.

## Never

- Set `flags.dangerously_skip_permissions` to `true`, or pass permission-bypass flags to the CLI.
- Store or log a GitHub token, or put one in a git remote URL.
- Let a sandbox workspace contain a `.git` remote or a credential.
- Import a specific adapter from core code; go through `adapters/loader.py`.
