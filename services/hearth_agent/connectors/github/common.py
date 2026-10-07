"""
GitHub connector — shared core, common to every auth method.

Both acquisition methods (a pasted fine-grained PAT via ``pat.py``, and the
``gh auth login`` device flow via ``cli_auth.py``) end with the token held by the
gh CLI. Everything *after* that point is identical, and lives here:

  - persistence  — provider key "github" in token.json (owned by token_store),
                   holding credential METADATA only: login, auth method, expiry,
                   last check. The token itself lives in gh's store (TDD §6).
  - validation   — GET /user, plus the fine-grained token's expiry header
  - status       — what the UI shows, including the 14-day expiry warning (PRD §5);
                   connected exactly when gh's active github.com account works
  - git identity — seed the space's global user.name / user.email for the bot, and
                   `gh auth setup-git` for HTTPS credentials; disconnecting removes
                   both, so the next account starts clean
  - one identity — gh keeps several accounts per host; connecting signs it out of
                   the others, disconnecting out of all of them

Shape mirrors xo-space ``connectors/github/common.py`` (including quirq-ai/xo-space#197:
token in gh's store, one gh account, git config cleared on disconnect).

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
GITHUB_HOSTNAME = "github.com"
EXPIRY_WARNING_DAYS = 14

GitHubStatus = Literal["connected", "needs_auth", "failed"]
AuthMethod = Literal["pat", "cli"]

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


# ---------------------------------------------------------------------------
# gh accounts: one identity per space
# ---------------------------------------------------------------------------

def gh_available() -> bool:
    return shutil.which(GH_BIN) is not None


async def sign_gh_out(gh: GhCli | None = None) -> None:
    """Sign gh out of every github.com account it holds. Never raises.

    A bare ``gh auth logout`` covers only one account, and fails outright once gh
    holds more than one; so each is named.
    """
    gh = gh or GhCli()
    accounts = await gh.accounts()
    if accounts is None:
        await gh.logout()  # gh cannot list its accounts: the bare logout, which covers one
        return
    for account in accounts:
        await gh.logout(account.login)


async def sign_gh_out_of_other_accounts(gh: GhCli | None = None) -> None:
    """After a sign-in: sign gh out of every github.com account but the one just made
    active, since `gh auth login` adds an account rather than replacing the last.
    The space holds one identity. Never raises."""
    gh = gh or GhCli()
    accounts = await gh.accounts()
    if accounts is None:
        log.warning("Could not list gh's github.com accounts; an earlier one may still be signed in")
        return
    active = next((a.login for a in accounts if a.active), None)
    if active is None:
        return  # nothing tells the new one apart, so keep all
    for account in accounts:
        if account.login != active:
            await gh.logout(account.login)


async def disconnect_github_account(gh: GhCli | None = None) -> bool:
    """Sign gh out of every github.com account, remove what connecting wrote to the
    global gitconfig, and forget the credential metadata. Never raises.

    Returns whether gh is left without a github.com account. Logging out only the
    active account is not enough: gh makes the next one active, and its token would
    still answer every `gh` call. Metadata is kept when gh is still signed in, so a
    failed disconnect leaves the record as it was.
    """
    gh = gh or GhCli()
    await sign_gh_out(gh)
    await _clear_git_config()
    remaining = await gh.accounts()
    signed_out = (await gh.auth_token() is None) if remaining is None else not remaining
    if signed_out:
        delete_entry("github")
        log.info("GitHub disconnected")
    else:
        log.warning("gh is still signed in to %s after disconnect", GITHUB_HOSTNAME)
    return signed_out


# ---------------------------------------------------------------------------
# Token validation
# ---------------------------------------------------------------------------

def _token_kind(token: str) -> str:
    if token.startswith("github_pat_"):
        return "fine_grained"
    if token.startswith("ghp_"):
        return "classic"
    if token.startswith("gho_"):
        return "oauth"  # from the `gh auth login` device flow
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
    if kind in ("classic", "other"):
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

    Connected exactly when gh's active github.com account works, whether HEARTH or a
    terminal signed it in. ``auth_method`` / ``expires_at`` come from the metadata only
    when it describes that same account; a terminal sign-in reports them as None.
    """
    gh = gh or GhCli()
    meta = get_github_credential() or {}
    accounts = await gh.accounts()
    auth = await gh.auth_status()
    if accounts is None:  # gh cannot list accounts: fall back to the plain status
        ok, login = auth.ok, auth.login
    else:
        active = next((a for a in accounts if a.active), None)
        ok = active is not None and active.state == "success"
        login = active.login if active else None
    if not ok:
        if meta:
            meta["healthy"] = False
            meta["checked_at"] = datetime.now(UTC).isoformat()
            set_entry("github", meta)
        return {"status": "needs_auth", "gh_status": auth.message}
    ours = bool(meta) and meta.get("login") == login
    result: dict[str, Any] = {
        "status": "connected",
        "username": login or "",
        "auth_method": meta.get("auth_method") if ours else None,
        "expires_at": meta.get("expires_at") if ours else None,
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


# What connecting writes to the global gitconfig: the identity above, and the
# credential helpers `gh auth setup-git` points at gh.
_GIT_KEYS_SET_ON_CONNECT = (
    "user.name",
    "user.email",
    f"credential.https://{GITHUB_HOSTNAME}.helper",
    "credential.https://gist.github.com.helper",
)


async def _clear_git_config() -> None:
    """Remove what connecting wrote to the global gitconfig. Never raises.

    The identity goes even when set by hand: otherwise connecting a different
    account keeps the previous name and email, and the bot's commits are credited
    to the wrong account. The next account to connect seeds its own. Other
    settings stay, and git drops a section once its last key is gone.
    """
    if shutil.which(GIT_BIN) is None:
        return
    for key in _GIT_KEYS_SET_ON_CONNECT:
        rc, out = await _run(GIT_BIN, "config", "--global", "--unset-all", key)
        if rc not in (0, 5):  # 5: the key was not set
            log.warning("Could not remove git %s: %s", key, out)


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
