"""
Shared CLI invocation for the per-agent status adapters.

The status adapters shell out to the agent's CLI and then interpret its output.
The *invocation* half is identical — resolve the binary, guard a missing absolute
path, spawn, enforce a timeout (killing the process on expiry), and decode
stdout/stderr — and lives here. The *interpretation* half (strict JSON vs. text,
which ``invalid_*`` code to raise) stays in each adapter.

    resolve_binary(env_var, default_bin) -> str
    run_cli(binary, args, *, timeout, label, env=None) -> CliResult

``run_cli`` raises :class:`CliStatusError` for ``binary_not_found`` / ``timeout``
and otherwise returns a :class:`CliResult`; it never judges the return code.

Shape mirrors xo-space ``adapters/cli_status.py``; it runs through
``utils.commands.run`` so the whole process group dies on a timeout.
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Sequence
from dataclasses import dataclass

from utils.commands import run


class CliStatusError(Exception):
    """CLI invocation/interpretation failure.

    ``code`` is mapped to an HTTP status by the /models/status and /channels/status
    routers: ``binary_not_found`` | ``timeout`` | ``execution_failed`` |
    ``invalid_json`` | ``invalid_output``.
    """

    def __init__(self, message: str, *, code: str, detail: str | None = None):
        super().__init__(message)
        self.code = code
        self.detail = detail


def resolve_binary(env_var: str, default_bin: str) -> str:
    """Env override → PATH lookup → bare command name."""
    configured = (os.getenv(env_var, "") or "").strip()
    return configured or shutil.which(default_bin) or default_bin


@dataclass
class CliResult:
    """Outcome of a completed CLI run; stdout/stderr decoded and stripped."""

    returncode: int
    stdout: str
    stderr: str


async def run_cli(
    binary: str,
    args: Sequence[str],
    *,
    timeout: float,
    label: str,
    env: dict[str, str] | None = None,
) -> CliResult:
    """Spawn ``binary args`` with a hard timeout and return the decoded result."""
    if os.path.isabs(binary) and not os.path.isfile(binary):
        raise CliStatusError(f"{label} binary not found at {binary}", code="binary_not_found", detail=binary)
    res = await run([binary, *args], timeout=timeout, env=env, separate_stderr=True)
    if res.binary_missing or res.exception is not None:
        raise CliStatusError(f"{label} binary unavailable: {binary}", code="binary_not_found",
                             detail=res.exception or binary)
    if res.timed_out:
        raise CliStatusError(f"{label} timed out after {timeout}s", code="timeout")
    return CliResult(returncode=res.returncode, stdout=res.stdout.strip(), stderr=res.stderr.strip())
