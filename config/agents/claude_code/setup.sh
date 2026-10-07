#!/usr/bin/env bash
# ==============================================================
# config/agents/claude_code/setup.sh — install + check the
# claude_code agent.
#
# Invoked by Hearth-Core's FastAPI lifespan (server.py) when
# AGENT_NAME=claude_code and HEARTH_SKIP_BOOT_INSTALL is not 1.
# In a space the CLI is preloaded in the image, so this is a no-op
# there; on a laptop it installs the CLI once. Every step is
# idempotent.
#
# Required env (jobs fail without one of these):
#     ANTHROPIC_API_KEY  or  CLAUDE_CODE_OAUTH_TOKEN  or  ANTHROPIC_AUTH_TOKEN (+ ANTHROPIC_BASE_URL)
#
# Shape mirrors xo-space config/agents/claude_code/setup.sh.
# ==============================================================

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MANIFEST="$SCRIPT_DIR/manifest.json"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

ok()   { echo -e "${GREEN}[claude_code]${NC} $*"; }
warn() { echo -e "${YELLOW}[claude_code]${NC} $*"; }
fail() { echo -e "${RED}[claude_code]${NC} $*"; }

NPM_PACKAGE="$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['runtime_setup']['npm_package'])" "$MANIFEST" 2>/dev/null || echo "@anthropic-ai/claude-code")"
CLI="${CLAUDE_CLI_PATH:-claude}"

# ── 1. CLI ────────────────────────────────────────────────────
if command -v "$CLI" >/dev/null 2>&1; then
  ok "claude CLI present: $("$CLI" --version 2>/dev/null | head -1)"
elif command -v npm >/dev/null 2>&1; then
  warn "claude CLI missing; installing $NPM_PACKAGE"
  if npm install -g "$NPM_PACKAGE" >/dev/null 2>&1; then
    ok "installed $NPM_PACKAGE"
  else
    fail "npm install -g $NPM_PACKAGE failed"
    exit 1
  fi
else
  fail "claude CLI missing and npm unavailable; install Node 20+ or preload the CLI in the space image"
  exit 1
fi

# ── 2. Auth ───────────────────────────────────────────────────
if [[ -n "${ANTHROPIC_API_KEY:-}" || -n "${CLAUDE_CODE_OAUTH_TOKEN:-}" || -n "${ANTHROPIC_AUTH_TOKEN:-}" ]]; then
  ok "LLM credential present"
elif [[ -f "$HOME/.claude/.credentials.json" ]]; then
  ok "native Claude login present"
else
  warn "no LLM credential: set ANTHROPIC_API_KEY, CLAUDE_CODE_OAUTH_TOKEN, or ANTHROPIC_AUTH_TOKEN + ANTHROPIC_BASE_URL"
fi

# ── 3. Home dir ───────────────────────────────────────────────
mkdir -p "$HOME/.claude"
exit 0
