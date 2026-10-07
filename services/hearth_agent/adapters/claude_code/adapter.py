from __future__ import annotations

import asyncio
import json
import logging
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from services.hearth_agent.adapters.base import BaseAgentAdapter, HarnessHooks
from services.hearth_agent.adapters.claude_code.hooks import build_hooks, deny_prompts
from services.hearth_agent.adapters.claude_code.mcp_tools import (
    DEFAULT_SERVER_NAME,
    JobState,
    build_domain_tools,
    build_server,
)
from services.hearth_agent.adapters.claude_code.prompts import MIGRATOR_RULES, build_task_message
from services.hearth_agent.adapters.claude_code.streaming import parse_message
from services.hearth_agent.engine import stream_events as se
from services.hearth_agent.models import AgentResult, JobSpec, Usage

log = logging.getLogger(__name__)

# Fallbacks when manifest.json leaves a field out.
_DEFAULT_MODEL = "claude-opus-5-5"
_DEFAULT_TOOLS = ["Read", "Edit", "Write", "Glob", "Grep", "Bash"]
_DEFAULT_DISALLOWED = ["WebFetch", "WebSearch", "Task"]


# ── Adapter class ──────────────────────────────────────────────────────────────


class ClaudeCodeAdapter(BaseAgentAdapter):
    """Claude Code, driven through the Claude Agent SDK, for one HEARTH job at a time.

    Shape mirrors xo-space ``adapters/claude_code/adapter.py``. What HEARTH changes:

    - permissions stay on: no ``--dangerously-skip-permissions``; the tool-layer
      policy runs in a ``PreToolUse`` hook (``hooks.py``) and prompts are denied;
    - the agent's tools are the manifest's ``flags.tools`` plus HEARTH's domain
      tools (``mcp_tools.py``); web tools and subagents are disallowed;
    - user/project settings files are not loaded (``setting_sources: []``), so the
      job config is the whole config;
    - ``finish`` only succeeds after an independent validation passes.
    """

    @property
    def adapter_name(self) -> str:
        return "claude_code"

    def __init__(self, config: dict[str, Any]):
        super().__init__(config)
        self.commands = self.load_commands()
        flags = self.commands.get("flags") or {}
        if flags.get("dangerously_skip_permissions"):
            raise ValueError("HEARTH never runs Claude Code with permissions bypassed; "
                             "set flags.dangerously_skip_permissions to false in manifest.json")

    # ── Manifest-driven settings ───────────────────────────────────────────────

    @property
    def _flags(self) -> dict[str, Any]:
        return self.commands.get("flags") or {}

    @property
    def _mcp_server(self) -> str:
        return (self.commands.get("mcp") or {}).get("server_name") or DEFAULT_SERVER_NAME

    def _model(self, job: JobSpec) -> str:
        model_cfg = self.commands.get("model") or {}
        return job.model or self.config.get("model") or model_cfg.get("default") or _DEFAULT_MODEL

    def _effort(self) -> str | None:
        return (self.commands.get("model") or {}).get("effort")

    def _cli_path(self) -> str | None:
        return self.config.get("cli_path") or None

    # ── Subprocess environment (ported from xo-space) ─────────────────────────

    def cli_env(self, hooks: HarnessHooks | None = None) -> dict[str, str]:
        """Environment the spawned ``claude`` runs with.

        From xo-space: drop empty/placeholder auth vars and OAuth tokens leaked into
        ``ANTHROPIC_API_KEY``, and let a usable native login win over static env
        tokens. HEARTH adds the space's LLM gateway and switches off non-essential
        traffic (no telemetry leaves the space).

        The SDK starts the CLI with ``{**os.environ, **options.env}``, so a variable
        is removed by overriding it with an empty string rather than omitting it.
        """
        env: dict[str, str] = {}
        for key in ("ANTHROPIC_API_KEY", "ANTHROPIC_OAUTH_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN"):
            value = os.environ.get(key)
            if value is None:
                continue
            if value == "sk-ant-none" or (key != "CLAUDE_CODE_OAUTH_TOKEN" and value.startswith("sk-ant-oat")):
                env[key] = ""
        if self._has_usable_native_login():
            for key in ("ANTHROPIC_API_KEY", "ANTHROPIC_OAUTH_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN"):
                if key in os.environ:
                    env[key] = ""
        if hooks is not None:
            env.update(hooks.llm_env)
            if hooks.llm_base_url:
                env["ANTHROPIC_BASE_URL"] = hooks.llm_base_url
        env["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] = "1"
        return env

    def _agent_home_dir(self) -> Path:
        return Path(os.path.expanduser(self.commands.get("home_dir") or "~/.claude"))

    def _has_usable_native_login(self) -> bool:
        """True when ``~/.claude/.credentials.json`` holds a refresh token or an unexpired access token."""
        for name in (".credentials.json", "credentials.json"):
            path = self._agent_home_dir() / name
            if not path.is_file():
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            oauth = data.get("claudeAiOauth") if isinstance(data, dict) else None
            if not isinstance(oauth, dict):
                oauth = data if isinstance(data, dict) else {}
            if oauth.get("refreshToken"):
                return True
            access, expires_at = oauth.get("accessToken"), oauth.get("expiresAt")
            if access and isinstance(expires_at, (int, float)):
                if expires_at / 1000 > datetime.now(UTC).timestamp():
                    return True
            elif access and expires_at is None:
                return True
        return False

    # ── SDK options ────────────────────────────────────────────────────────────

    def build_options(self, job: JobSpec, workspace: Path, hooks: HarnessHooks, state: JobState, emit):
        from claude_agent_sdk import ClaudeAgentOptions

        tools = list(self._flags.get("tools") or _DEFAULT_TOOLS)
        server = self._mcp_server
        return ClaudeAgentOptions(
            cwd=str(workspace),
            model=self._model(job),
            effort=self._effort(),  # type: ignore[arg-type]
            system_prompt={"type": "preset", "preset": "claude_code", "append": MIGRATOR_RULES},
            tools=tools,
            allowed_tools=[*tools, f"mcp__{server}__*"],
            disallowed_tools=list(self._flags.get("disallowed_tools") or _DEFAULT_DISALLOWED),
            mcp_servers={server: build_server(build_domain_tools(job, hooks, state, emit), server)},
            hooks=build_hooks(workspace, hooks.policy, state, emit, mcp_server=server),
            can_use_tool=deny_prompts,
            permission_mode=self._flags.get("permission_mode", "default"),
            setting_sources=list(self._flags.get("setting_sources", [])),
            max_turns=job.limits.max_steps,
            env=self.cli_env(hooks),
            user=hooks.run_as_user,
            cli_path=self._cli_path(),
        )

    # ── BaseAgentAdapter implementation ───────────────────────────────────────

    async def stream(self, job: JobSpec, workspace: Path, hooks: HarnessHooks) -> AsyncIterator[dict[str, Any]]:
        import claude_agent_sdk

        queue: asyncio.Queue[dict | None] = asyncio.Queue()
        state = JobState()
        usage = Usage()
        native_session_id: str | None = None

        async def emit(event: dict) -> None:
            await queue.put(event)

        options = self.build_options(job, workspace, hooks, state, emit)

        async def prompts():
            yield {"type": "user", "message": {"role": "user", "content": build_task_message(job)}}

        async def produce() -> None:
            nonlocal native_session_id
            try:
                async for msg in claude_agent_sdk.query(prompt=prompts(), options=options):
                    if isinstance(msg, claude_agent_sdk.AssistantMessage):
                        usage.steps += 1
                    for event in parse_message(msg):
                        if event["type"] == se.SESSION_ID:
                            native_session_id = event["session_id"]
                        elif event["type"] == se.RESULT:
                            u = event.get("usage") or {}
                            usage.input_tokens = int(u.get("input_tokens", 0)) + int(u.get("cache_read_input_tokens", 0))
                            usage.output_tokens = int(u.get("output_tokens", 0))
                            usage.cost_usd = event.get("total_cost_usd")
                            usage.steps = event.get("num_turns") or usage.steps
                            native_session_id = event.get("session_id") or native_session_id
                        await emit(event)
                    if state.finished or state.out_of_rounds:
                        break
                    if usage.input_tokens + usage.output_tokens > job.limits.max_tokens:
                        await emit(se.error("token budget exhausted"))
                        break
            except Exception as exc:  # SDK / CLI failure: report, never raise into the harness
                log.exception("claude code run failed")
                await emit(se.error(f"{type(exc).__name__}: {exc}"))
            finally:
                await queue.put(None)

        task = asyncio.create_task(produce())
        timed_out = False
        try:
            async with asyncio.timeout(job.limits.wall_clock_seconds):
                while (event := await queue.get()) is not None:
                    yield event
        except TimeoutError:
            timed_out = True
        finally:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)

        if state.finished:
            status = "passed"
        elif timed_out or (usage.steps >= job.limits.max_steps and not state.out_of_rounds):
            status = "budget_exhausted"
        else:
            status = "failed_fix"
        result = AgentResult(
            job_id=job.job_id,
            intelligence=self.adapter_name,
            status=status,  # type: ignore[arg-type]
            summary=state.summary,
            needs_human_attention=state.needs_attention,
            validation=state.last_validation,
            usage=usage,
            native_session_id=native_session_id,
            finished_at=datetime.now(UTC),
            extra={"policy_violations": state.policy_violations, "validation_rounds": state.validation_rounds},
        )
        yield se.done(native_session_id, result.model_dump(mode="json"))

    async def health(self) -> dict[str, Any]:
        cli = self._cli_path() or self.commands.get("binary") or "claude"
        try:
            proc = await asyncio.create_subprocess_exec(
                cli, "--version", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
            return {"ok": proc.returncode == 0, "version": stdout.decode().strip()}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}


# Stable discovery alias — the dynamic loader resolves
# services.hearth_agent.adapters.<AGENT_NAME>.adapter.Adapter.
Adapter = ClaudeCodeAdapter
