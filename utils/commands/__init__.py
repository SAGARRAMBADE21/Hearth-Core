"""The single external-command executor.

Every subprocess HEARTH starts goes through :func:`run`: an argv list (never a
string, never ``shell=True``), stdin closed unless ``input`` is given so nothing
can hang on a prompt, a timeout that kills the whole process group (so
grandchildren die too), and secrets redacted from anything logged.

Shape mirrors xo-space ``utils/commands`` (``CommandResult``, ``run``,
``safe_arg``) so call sites read the same in both codebases.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import signal
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class CommandResult:
    """Outcome of one subprocess run.

    ``returncode`` is -1 when no process ran or its code is unknown (binary not
    found, a local exception). Check ``ok`` rather than testing for 0 directly
    when you want "finished cleanly".
    """

    argv: list[str]
    returncode: int
    output: str  # stdout (+ stderr merged unless separate_stderr was requested)
    duration_seconds: float
    timed_out: bool = False
    binary_missing: bool = False
    exception: str | None = None
    stderr: str = ""  # populated only when separate_stderr=True

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and not self.timed_out and not self.binary_missing

    @property
    def stdout(self) -> str:
        """Alias for ``output``, so call sites ported from ``subprocess.run`` keep reading ``.stdout``."""
        return self.output


# ── Redaction ────────────────────────────────────────────────────────────────

_SENSITIVE_FLAGS = ("--token", "--api-key", "--password", "--secret", "--with-token")
_SECRET_PATTERNS = (
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"sk-ant-[A-Za-z0-9_\-]{10,}"),
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"(?i)(authorization:\s*(?:basic|bearer)\s+)\S+"),
)


def redact(text: str) -> str:
    """Mask tokens and Authorization headers in free text."""
    for pat in _SECRET_PATTERNS:
        text = pat.sub(lambda m: (m.group(1) if m.groups() else "") + "***", text)
    return text


def redact_argv(argv: Sequence[str]) -> list[str]:
    out: list[str] = []
    hide_next = False
    for token in argv:
        if hide_next:
            out.append("***")
            hide_next = False
            continue
        if token in _SENSITIVE_FLAGS:
            hide_next = True
        elif any(token.startswith(f + "=") for f in _SENSITIVE_FLAGS):
            token = token.split("=", 1)[0] + "=***"
        out.append(redact(token))
    return out


# ── Argument safety ──────────────────────────────────────────────────────────


class CommandSpecError(ValueError):
    pass


def safe_arg(value: Any, *, allow_option: bool = False) -> str:
    """Refuse values that could be read as an option (argument injection) or carry a NUL byte."""
    text = str(value)
    if "\x00" in text:
        raise CommandSpecError("argument contains a NUL byte")
    if not allow_option and text.startswith("-"):
        raise CommandSpecError(f"argument may not start with '-': {text!r}")
    return text


# ── Execution ────────────────────────────────────────────────────────────────


def _kill_tree(proc: asyncio.subprocess.Process) -> None:
    try:
        if sys.platform != "win32":
            os.killpg(proc.pid, signal.SIGKILL)
        else:
            proc.kill()
    except (ProcessLookupError, PermissionError):
        pass


async def run(
    argv: Sequence[str],
    *,
    cwd: str | Path | None = None,
    timeout: float | None = None,
    env: dict[str, str] | None = None,
    input: bytes | str | None = None,
    separate_stderr: bool = False,
) -> CommandResult:
    """Run a command asynchronously and return a :class:`CommandResult`. Never raises for process failures.

    argv:            command + args as a list — never a string (no shell).
    cwd:             working directory for the child process.
    timeout:         seconds before the process group is killed. ``None`` = no timeout.
    env:             environment overrides merged onto the parent's.
    input:           written to the child's stdin; without it stdin is /dev/null.
    separate_stderr: keep stderr apart (``result.stderr``) instead of merging it into ``output``.
    """
    argv = [str(a) for a in argv]
    started = time.monotonic()
    log.debug("exec %s", redact_argv(argv))
    full_env = {**os.environ, **(env or {})}
    full_env.setdefault("GIT_TERMINAL_PROMPT", "0")
    kwargs: dict[str, Any] = {"start_new_session": True} if sys.platform != "win32" else {}
    data = input.encode() if isinstance(input, str) else input
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            cwd=str(cwd) if cwd else None,
            env=full_env,
            stdin=asyncio.subprocess.PIPE if data is not None else asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE if separate_stderr else asyncio.subprocess.STDOUT,
            **kwargs,
        )
    except FileNotFoundError:
        return CommandResult(argv, -1, f"binary not found: {argv[0]}", 0.0, binary_missing=True)
    except OSError as exc:
        return CommandResult(argv, -1, str(exc), 0.0, exception=str(exc))

    try:
        out, err = await asyncio.wait_for(proc.communicate(data), timeout=timeout)
    except TimeoutError:
        _kill_tree(proc)
        await proc.wait()
        return CommandResult(argv, proc.returncode if proc.returncode is not None else -1, "timed out",
                             time.monotonic() - started, timed_out=True)
    return CommandResult(
        argv,
        proc.returncode if proc.returncode is not None else -1,
        (out or b"").decode(errors="replace"),
        time.monotonic() - started,
        stderr=(err or b"").decode(errors="replace") if separate_stderr else "",
    )
