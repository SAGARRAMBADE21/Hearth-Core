"""Git Host Poller primitives (TDD §9): ETag-conditional polling with since-cursors.

The space accepts no inbound webhooks, so it polls. A 304 costs no rate limit; cursors persist in the
repository's JSON record so polling catches up after downtime. Scheduling (Temporal cron) lives in the
backend; this module only performs one poll step and returns the new cursor.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .gh_api import GhCli, GhErrorKind


@dataclass
class PollCursor:
    etag_head: str | None = None
    head_sha: str | None = None
    etag_comments: str | None = None
    comments_since: str | None = None  # ISO-8601


@dataclass
class PollOutcome:
    cursor: PollCursor
    new_head_sha: str | None = None
    new_comments: list[dict[str, Any]] = field(default_factory=list)
    rate_remaining: int | None = None
    error: GhErrorKind | None = None


async def poll_default_branch(gh: GhCli, repo: str, branch: str, cursor: PollCursor) -> PollOutcome:
    r = await gh.api(f"repos/{repo}/commits/{branch}", etag=cursor.etag_head)
    if r.kind == GhErrorKind.NOT_MODIFIED:
        return PollOutcome(cursor, rate_remaining=r.rate.remaining)
    if not r.ok:
        return PollOutcome(cursor, error=r.kind, rate_remaining=r.rate.remaining)
    sha = r.data["sha"]
    new = PollCursor(r.etag, sha, cursor.etag_comments, cursor.comments_since)
    return PollOutcome(new, new_head_sha=sha if sha != cursor.head_sha else None, rate_remaining=r.rate.remaining)


async def poll_pr_comments(gh: GhCli, repo: str, cursor: PollCursor, *, bot_login: str) -> PollOutcome:
    """New issue comments repo-wide since the cursor, excluding the bot's own (it can't drive itself)."""
    path = f"repos/{repo}/issues/comments?sort=updated&direction=asc&per_page=100"
    if cursor.comments_since:
        path += f"&since={cursor.comments_since}"
    r = await gh.api(path, etag=cursor.etag_comments)
    if r.kind == GhErrorKind.NOT_MODIFIED:
        return PollOutcome(cursor, rate_remaining=r.rate.remaining)
    if not r.ok:
        return PollOutcome(cursor, error=r.kind, rate_remaining=r.rate.remaining)
    comments = [c for c in (r.data or []) if (c.get("user") or {}).get("login") != bot_login]
    since = max((c["updated_at"] for c in r.data or []), default=cursor.comments_since)
    new = PollCursor(cursor.etag_head, cursor.head_sha, r.etag, since)
    return PollOutcome(new, new_comments=comments, rate_remaining=r.rate.remaining)
