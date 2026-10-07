# Hearth-Core

HEARTH's core service: the **GitHub connector**, the **API diff engine**, and the **Claude Code adapter**.
It runs inside every HEARTH space, next to Hearth-backend's engine services.

## Layout

The tree mirrors xo-space's shape so the two codebases read the same:

```
config/agents/claude_code/      manifest.json, capabilities.json, settings.json, setup.sh
routers/hearth_agent/           thin APIRouters: agents.py, apidiff.py, connectors/github_pat.py
services/hearth_agent/
  adapters/                     base.py, loader.py, claude_code/{adapter,streaming,mcp_tools,hooks,prompts}.py
  connectors/                   token_store.py, github/{common,pat,gh_api,repo,pulls,poller,bot}.py
  engine/                       dispatcher.py, stream_events.py
  registry/                     agent_registry.py, adapter_registry.py, settings.py
  models.py, policy.py          shared records; tool-layer policy
services/apidiff/               OpenAPI / Python / TypeScript surface extraction and diff → Change Record
services/storage/               the machine-local state root ($HEARTH_STATE_DIR)
utils/commands/                 the single subprocess executor
server.py                       FastAPI app
tests/                          unittest suite
```

## API

| Method | Path | What it does |
|---|---|---|
| GET | `/health` | liveness |
| GET | `/api/agents` · `/api/agents/health` · `/api/agents/capabilities` | agent framework |
| POST | `/api/apidiff` | diff two API surfaces given inline |
| POST | `/api/connectors/github/token` | validate a fine-grained PAT and hand it to gh |
| GET | `/api/connectors/github/status` | `gh auth status` + metadata + expiry warning |
| POST | `/api/connectors/github/disconnect` · `/reconnect` | log out / re-validate |

## Run

```bash
./hearth-core.sh install && ./hearth-core.sh dev     # http://127.0.0.1:5010
./hearth-core.sh test
python -m services.apidiff.cli old.yaml new.yaml     # CLI diff
```

## Notices

Portions of the structure and of `connectors/token_store.py`, `connectors/github/{common,pat}.py`,
`adapters/{base,loader}.py`, `registry/*`, `engine/{dispatcher,stream_events}.py` and
`routers/hearth_agent/connectors/github_pat.py` are adapted from xo-space,
Copyright (c) 2026 XO Labs, Inc., used under the MIT License.
