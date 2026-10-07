"""Typed wrapper over the gh CLI, with every failure classified.

Owned by the PR Service process only: gh holds the token (``gh auth login
--with-token``), so nothing here ever sees, logs or forwards it. Mirrors the
``GhResult`` / error-kind pattern of xo-space ``connectors/github/issues.py``,
extended with the REST calls a HEARTH job needs (PRs, statuses, issues, ETags).
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Literal

from utils.commands import CommandResult, run, safe_arg

CommitState = Literal["pending", "success", "failure", "error"]


# ── Results ──────────────────────────────────────────────────────────────────


class GhErrorKind(StrEnum):
    NO_CLI = "no_cli"
    TIMEOUT = "timeout"
    NOT_AUTHENTICATED = "not_authenticated"
    RATE_LIMITED = "rate_limited"
    FORBIDDEN = "forbidden"
    NOT_FOUND = "not_found"
    NOT_MODIFIED = "not_modified"  # ETag hit: costs no rate limit
    CONFLICT = "conflict"
    NETWORK = "network"
    BAD_RESPONSE = "bad_response"
    ERROR = "error"


@dataclass(frozen=True)
class RateLimit:
    limit: int | None = None
    remaining: int | None = None
    reset_epoch: int | None = None


@dataclass
class GhResult:
    ok: bool
    data: Any = None
    kind: GhErrorKind | None = None
    message: str = ""
    status: int | None = None
    headers: dict[str, str] = field(default_factory=dict)

    @property
    def etag(self) -> str | None:
        return self.headers.get("etag")

    @property
    def rate(self) -> RateLimit:
        def _int(k: str) -> int | None:
            v = self.headers.get(k)
            return int(v) if v and v.isdigit() else None

        return RateLimit(_int("x-ratelimit-limit"), _int("x-ratelimit-remaining"), _int("x-ratelimit-reset"))


_STATUS_RE = re.compile(r"HTTP (\d{3})")


def classify(result: CommandResult, status: int | None = None) -> GhErrorKind:
    if result.binary_missing:
        return GhErrorKind.NO_CLI
    if result.timed_out:
        return GhErrorKind.TIMEOUT
    if result.returncode == 4:  # gh's exit code for "authentication required"
        return GhErrorKind.NOT_AUTHENTICATED
    text = (result.stderr + result.output).lower()
    if status is None:
        m = _STATUS_RE.search(result.stderr)
        status = int(m.group(1)) if m else None
    if status == 304:
        return GhErrorKind.NOT_MODIFIED
    if status == 401 or "gh auth login" in text or "authentication required" in text:
        return GhErrorKind.NOT_AUTHENTICATED
    if status == 429 or "rate limit" in text:
        return GhErrorKind.RATE_LIMITED
    if status == 403:
        return GhErrorKind.FORBIDDEN
    if status == 404 or "not found" in text:
        return GhErrorKind.NOT_FOUND
    if status in (409, 422):
        return GhErrorKind.CONFLICT
    if any(s in text for s in ("could not resolve", "connection refused", "tls handshake", "i/o timeout")):
        return GhErrorKind.NETWORK
    return GhErrorKind.ERROR


def _parse_include_output(stdout: str) -> tuple[int | None, dict[str, str], str]:
    """Split ``gh api --include`` output into (status, lower-cased headers, body)."""
    text = stdout.replace("\r\n", "\n")
    head, sep, body = text.partition("\n\n")
    if not sep or not head.startswith("HTTP/"):
        return None, {}, stdout
    lines = head.split("\n")
    parts = lines[0].split()
    status = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else None
    headers: dict[str, str] = {}
    for line in lines[1:]:
        k, _, v = line.partition(":")
        if k:
            headers[k.strip().lower()] = v.strip()
    return status, headers, body


# ── Client ───────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class AuthStatus:
    ok: bool
    host: str
    login: str | None
    message: str


class GhCli:
    def __init__(self, *, host: str = "github.com", binary: str = "gh", env: Mapping[str, str] | None = None):
        self.host = host
        self.binary = binary
        self.env = dict(env or {})

    async def _gh(self, args: Sequence[str], *, input: str | None = None, timeout: float = 120) -> CommandResult:
        return await run([self.binary, *args], env={"GH_PROMPT_DISABLED": "1", **self.env}, input=input,
                         timeout=timeout, separate_stderr=True)

    # -- auth ----------------------------------------------------------------

    async def login_with_token(self, token: str) -> GhResult:
        """``gh auth login --with-token`` (token on stdin) then ``gh auth setup-git`` (TDD §9)."""
        r = await self._gh(["auth", "login", "--hostname", self.host, "--git-protocol", "https", "--with-token"],
                           input=token.strip() + "\n")
        if not r.ok:
            return GhResult(False, kind=classify(r), message=r.stderr.strip())
        r = await self._gh(["auth", "setup-git", "--hostname", self.host])
        if not r.ok:
            return GhResult(False, kind=classify(r), message=r.stderr.strip())
        return GhResult(True)

    async def auth_status(self) -> AuthStatus:
        r = await self._gh(["auth", "status", "--hostname", self.host])
        text = r.stdout + r.stderr
        login = None
        for line in text.splitlines():
            if "Logged in to" in line and " account " in line:
                login = line.split(" account ", 1)[1].split()[0]
        return AuthStatus(r.ok, self.host, login, text.strip())

    async def auth_token(self) -> str | None:
        """The token gh holds, for a one-off validation call. Never persist or log it."""
        r = await self._gh(["auth", "token", "--hostname", self.host])
        return (r.stdout.strip() or None) if r.ok else None

    async def logout(self) -> GhResult:
        r = await self._gh(["auth", "logout", "--hostname", self.host])
        return GhResult(r.ok, kind=None if r.ok else classify(r), message=r.stderr.strip())

    # -- REST ----------------------------------------------------------------

    async def api(
        self,
        path: str,
        *,
        method: str = "GET",
        fields: Mapping[str, Any] | None = None,
        etag: str | None = None,
        paginate: bool = False,
    ) -> GhResult:
        """``gh api`` with status/headers parsed. Pass ``etag`` for a conditional request (304 is free)."""
        args = ["api", "--hostname", self.host, "--include", "-X", method, safe_arg(path.lstrip("/"))]
        if etag:
            args += ["-H", f"If-None-Match: {etag}"]
        if paginate:
            args.append("--paginate")
        body: str | None = None
        if fields:
            args += ["--input", "-"]
            body = json.dumps(fields)
        r = await self._gh(args, input=body)
        status, headers, raw = _parse_include_output(r.stdout)
        if status == 304:
            return GhResult(False, kind=GhErrorKind.NOT_MODIFIED, status=304, headers=headers)
        if not r.ok or (status is not None and status >= 400):
            return GhResult(False, kind=classify(r, status), message=(r.stderr or raw).strip()[:2000],
                            status=status, headers=headers)
        try:
            data = json.loads(raw) if raw.strip() else None
        except json.JSONDecodeError:
            return GhResult(False, kind=GhErrorKind.BAD_RESPONSE, message=raw[:500], status=status, headers=headers)
        return GhResult(True, data=data, status=status, headers=headers)

    async def rate_limit(self) -> GhResult:
        return await self.api("rate_limit")

    # -- pull requests, statuses, issues ---------------------------------------

    async def create_pull_request(
        self, repo: str, *, head: str, base: str, title: str, body: str, draft: bool = False,
        labels: Sequence[str] = (), reviewers: Sequence[str] = (),
    ) -> GhResult:
        r = await self.api(f"repos/{repo}/pulls", method="POST",
                           fields={"head": head, "base": base, "title": title, "body": body, "draft": draft})
        if not r.ok:
            return r
        number = r.data["number"]
        if labels:
            await self.api(f"repos/{repo}/issues/{number}/labels", method="POST", fields={"labels": list(labels)})
        users = [u.lstrip("@") for u in reviewers if "/" not in u]
        teams = [u.split("/", 1)[1] for u in reviewers if "/" in u]
        if users or teams:
            await self.api(f"repos/{repo}/pulls/{number}/requested_reviewers", method="POST",
                           fields={"reviewers": users, "team_reviewers": teams})
        return r

    async def set_commit_status(
        self, repo: str, sha: str, state: CommitState, *, description: str, target_url: str | None = None,
        context: str = "HEARTH",
    ) -> GhResult:
        fields: dict[str, Any] = {"state": state, "description": description[:140], "context": context}
        if target_url:
            fields["target_url"] = target_url
        return await self.api(f"repos/{repo}/statuses/{safe_arg(sha)}", method="POST", fields=fields)

    async def create_issue(self, repo: str, *, title: str, body: str, labels: Sequence[str] = ()) -> GhResult:
        return await self.api(f"repos/{repo}/issues", method="POST",
                              fields={"title": title, "body": body, "labels": list(labels)})

    async def comment(self, repo: str, number: int, body: str) -> GhResult:
        return await self.api(f"repos/{repo}/issues/{number}/comments", method="POST", fields={"body": body})

    async def close_pull_request(self, repo: str, number: int) -> GhResult:
        return await self.api(f"repos/{repo}/pulls/{number}", method="PATCH", fields={"state": "closed"})

    async def is_org_member(self, org: str, login: str) -> bool:
        """Bot commands are accepted only from org members (TDD §9)."""
        r = await self.api(f"orgs/{safe_arg(org)}/members/{safe_arg(login)}")
        return r.ok or r.status == 204
