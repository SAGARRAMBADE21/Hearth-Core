"""
GitHub connector — shared core, common to every auth method.

The acquisition method (a pasted fine-grained PAT via ``pat.py``) ends with the
token handed to the gh CLI. Everything *after* that point lives here:

  - persistence  — provider key "github" in token.json (owned by token_store),
                   holding credential METADATA only: login, auth method, expiry,
                   last check. The token itself lives in gh's store (TDD §6).
  - validation   — GET /user, plus the fine-grained token's expiry header
  - status       — what the UI shows, including the 14-day expiry warning (PRD §5)
  - git identity — seed the space's global user.name / user.email for the bot

Shape mirrors xo-space ``connectors/github/common.py``.

Token file: $HEARTH_STATE_DIR/secrets/token.json  (see connectors/token_store.py)
"""

import logging
import shutil
from datetime import UTC, datetime
from typing import Any, Literal

import httpx

from utils.commands import run

from ..token_store import delete_entry, get_entry, set_entry, token_file
from .gh_api import GhCli

log = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"
EXPIRY_WARNING_DAYS = 14

GitHubStatus = Literal["connected", "needs_auth", "failed"]
AuthMethod = Literal["pat"]

# Classic-PAT scopes HEARTH must never hold (PRD §5: never admin or branch-protection bypass).
_FORBIDDEN_SCOPES = {"admin:org", "admin:repo_hook", "admin:enterprise", "delete_repo", "site_admin"}


# ---------------------------------------------------------------------------
# Credential metadata (provider key "github" in token.json)
# ---------------------------------------------------------------------------

def get_github_credential(*, read_only: bool = False) -> dict[str, Any] | None:
    """Return the stored credential metadata (never a token), or None."""
    return get_entry("github", read_only=read_only)


def get_github_auth_method() -> str | None:
    entry = get_entry("github")
    return (entry or {}).get("auth_method") or None


async def get_github_token(gh: GhCli | None = None) -> str | None:
    """The token gh holds, read on demand for a validation call. Never stored by HEARTH."""
    return await (gh or GhCli()).auth_token()


def save_github_credential(validation: dict[str, Any], *, auth_method: str = "pat") -> None:
    """Persist what the UI and the hourly health check need — not the token."""
    set_entry("github", {
        "host": "github.com",
        "login": validation.get("username", ""),
        "token_kind": validation.get("token_kind", ""),
        "expires_at": validation.get("expires_at"),
        "scopes": validation.get("scopes", ""),
        "auth_method": auth_method,
        "secret_ref": "gh:github.com",  # where the token actually lives
        "checked_at": datetime.now(UTC).isoformat(),
        "healthy": True,
    })
    log.info("GitHub credential metadata saved to %s (method=%s)", token_file(), auth_method)


async def delete_github_credential(gh: GhCli | None = None) -> None:
    """Forget the credential: log gh out and remove the metadata entry."""
    await (gh or GhCli()).logout()
    delete_entry("github")
    log.info("GitHub credential removed")


# ---------------------------------------------------------------------------
# Token validation
# ---------------------------------------------------------------------------

def _token_kind(token: str) -> str:
    if token.startswith("github_pat_"):
        return "fine_grained"
    if token.startswith("ghp_"):
        return "classic"
    return "other"


def _parse_expiry(header: str) -> str | None:
    """GitHub sends e.g. ``2026-12-01 00:00:00 UTC`` for tokens with an expiry."""
    if not header:
        return None
    try:
        return datetime.strptime(header.replace(" UTC", ""), "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC).isoformat()
    except ValueError:
        return None


async def validate_token(token: str) -> dict[str, Any]:
    """
    Validate a GitHub token by calling /user.

    Returns:
        {
            "valid": True/False,
            "status": "connected" | "needs_auth" | "failed",
            "username": "...", "name": "...", "avatar_url": "...",   # if valid
            "token_kind": "fine_grained" | "classic" | "other",
            "expires_at": ISO-8601 | None,
            "scopes": "...",                                          # classic PATs only
            "warnings": [...],
            "error": "...",                                           # if not valid
        }
    """
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{GITHUB_API}/user",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
            )
    except httpx.TimeoutException:
        return {"valid": False, "status": "failed",
                "error": "Timed out connecting to GitHub. Check your internet connection."}
    except Exception as exc:
        return {"valid": False, "status": "failed", "error": f"Could not connect to GitHub: {exc}"}

    if resp.status_code in (401, 403):
        return {"valid": False, "status": "needs_auth", "error": "Token is invalid or revoked."}
    if resp.status_code != 200:
        return {"valid": False, "status": "failed", "error": f"GitHub returned HTTP {resp.status_code}."}

    user = resp.json()
    scopes = resp.headers.get("x-oauth-scopes", "")
    kind = _token_kind(token)
    warnings: list[str] = []
    granted = {s.strip() for s in scopes.split(",") if s.strip()}
    if granted & _FORBIDDEN_SCOPES:
        return {"valid": False, "status": "failed",
                "error": f"Token has admin scopes HEARTH must not hold: {', '.join(sorted(granted & _FORBIDDEN_SCOPES))}."}
    if kind != "fine_grained":
        warnings.append("Use a fine-grained token limited to the repositories HEARTH should maintain.")
    return {
        "valid": True,
        "status": "connected",
        "username": user.get("login", ""),
        "name": user.get("name", ""),
        "avatar_url": user.get("avatar_url", ""),
        "scopes": scopes,
        "token_kind": kind,
        "expires_at": _parse_expiry(resp.headers.get("github-authentication-token-expiration", "")),
        "warnings": warnings,
        # Used only to seed the local git identity; not part of the connection payload.
        "user_id": user.get("id"),
        "email": user.get("email") or "",
    }


def expiry_warning(expires_at: str | None, *, now: datetime | None = None) -> str | None:
    """Warn ``EXPIRY_WARNING_DAYS`` before the token expires (PRD §5)."""
    if not expires_at:
        return None
    try:
        exp = datetime.fromisoformat(expires_at)
    except ValueError:
        return None
    days = (exp - (now or datetime.now(UTC))).days
    if days < 0:
        return "The GitHub token has expired. Paste a new one."
    if days <= EXPIRY_WARNING_DAYS:
        return f"The GitHub token expires in {days} day(s). Paste a new one before then."
    return None


async def get_status(gh: GhCli | None = None) -> dict[str, Any]:
    """
    Compute the current GitHub connector status from gh (the source of truth for the
    token) plus the stored metadata. Shape: ``status``, ``username``, ``auth_method``,
    ``expires_at``, ``warning``, and ``gh_status`` (the ``gh auth status`` text the UI shows).
    """
    gh = gh or GhCli()
    meta = get_github_credential() or {}
    auth = await gh.auth_status()
    if not auth.ok:
        if meta:
            meta["healthy"] = False
            meta["checked_at"] = datetime.now(UTC).isoformat()
            set_entry("github", meta)
        return {"status": "needs_auth", "gh_status": auth.message}
    result: dict[str, Any] = {
        "status": "connected",
        "username": auth.login or meta.get("login", ""),
        "auth_method": meta.get("auth_method", "pat"),
        "expires_at": meta.get("expires_at"),
        "gh_status": auth.message,
    }
    warning = expiry_warning(meta.get("expires_at"))
    if warning:
        result["warning"] = warning
    return result


# ---------------------------------------------------------------------------
# Local git identity
# ---------------------------------------------------------------------------
#
# Connecting GitHub gives gh a token, but git itself still has no idea who the
# bot is; in a fresh space `~/.gitconfig` does not exist and the PR Service's
# first commit dies with "Author identity unknown". Seed it from the validated
# account (ideally a dedicated machine user such as hearth-bot).

GIT_BIN = "git"
GH_BIN = "gh"
_SUBPROCESS_TIMEOUT_SECONDS = 10


async def _run(*args: str) -> tuple[int, str]:
    """Run a command; return (returncode, output). Never raises."""
    res = await run(list(args), timeout=_SUBPROCESS_TIMEOUT_SECONDS)
    if res.timed_out or res.binary_missing or res.exception is not None:
        log.warning("Command %s failed: %s", args[0], res.output.strip())
        return 1, ""
    return res.returncode, res.output.strip()


def commit_email(validation: dict[str, Any]) -> str:
    """Best commit email for the account; falls back to the noreply form GitHub still attributes."""
    email = (validation.get("email") or "").strip()
    if email:
        return email
    login = (validation.get("username") or "").strip()
    if not login:
        return ""
    user_id = validation.get("user_id")
    if user_id:
        return f"{user_id}+{login}@users.noreply.github.com"
    return f"{login}@users.noreply.github.com"


async def configure_git_identity(validation: dict[str, Any]) -> None:
    """Seed the global git identity from a freshly validated account. Best-effort, never overwrites."""
    if shutil.which(GIT_BIN) is None:
        log.warning("git is not installed; skipping git identity setup")
        return
    name = (validation.get("name") or validation.get("username") or "").strip()
    email = commit_email(validation)
    for key, value in (("user.name", name), ("user.email", email)):
        if not value:
            continue
        rc, existing = await _run(GIT_BIN, "config", "--global", "--get", key)
        if rc == 0 and existing:
            log.info("git %s already set to %r; leaving it alone", key, existing)
            continue
        rc, out = await _run(GIT_BIN, "config", "--global", key, value)
        if rc != 0:
            log.warning("Could not set git %s: %s", key, out)


def connection_payload(validation: dict[str, Any], auth_method: str) -> dict[str, Any]:
    """Shape a successful validation into the response body the routes return."""
    payload = {
        "status": "connected",
        "auth_method": auth_method,
        "username": validation.get("username", ""),
        "name": validation.get("name", ""),
        "avatar_url": validation.get("avatar_url", ""),
        "token_kind": validation.get("token_kind", ""),
        "expires_at": validation.get("expires_at"),
        "warnings": validation.get("warnings", []),
    }
    warning = expiry_warning(validation.get("expires_at"))
    if warning:
        payload["warnings"] = [*payload["warnings"], warning]
    return payload
