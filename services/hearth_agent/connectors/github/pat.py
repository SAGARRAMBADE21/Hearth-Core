"""
GitHub connector — PAT (Personal Access Token) acquisition.

No OAuth app. The customer creates a fine-grained PAT (ideally on a dedicated
machine user such as ``hearth-bot``) limited to the repositories HEARTH should
maintain, with Contents, Pull requests, Issues and Commit statuses read/write and
Metadata read — never Administration — and pastes it into the HEARTH UI once.
This module validates it and signs the GitHub CLI in with it, the
non-interactive equivalent of::

    gh auth login --with-token < token.txt
    gh auth setup-git

so the token lives in gh's credential store and git borrows it through
`gh auth git-credential`, exactly as after the device flow. Only metadata is
written to token.json (PRD §7 onboarding step 2).

This is one of two acquisition methods; the other is the `gh auth login` device
flow in ``cli_auth.py``. Everything the two share lives in ``common.py``.

Shape mirrors xo-space ``connectors/github/pat.py`` (as of quirq-ai/xo-space#197).
"""

import logging
import re
from typing import Any

from .common import (
    configure_git_identity,
    connection_payload,
    gh_available,
    save_github_credential,
    sign_gh_out_of_other_accounts,
    validate_token,
)
from .gh_api import GhCli, GhErrorKind

log = logging.getLogger(__name__)

AUTH_METHOD = "pat"

# Prefixes GitHub uses for tokens a user can paste: classic PAT (ghp_),
# fine-grained PAT (github_pat_), OAuth token (gho_).
_TOKEN_PREFIXES = ("ghp_", "github_pat_", "gho_")
_MIN_TOKEN_LENGTH = 30

# `gh auth login` refuses a token that carries OAuth scopes (a classic PAT,
# including the old 40-hex kind, or an OAuth token) unless it has `repo` and
# `read:org`; `write:org` and `admin:org` include `read:org`. Fine-grained PATs
# have no scopes and are not checked. This is gh's own rule, applied before gh
# sees the token so the refusal can name every missing scope at once.
_SCOPED_TOKEN_RE = re.compile(r"(?:ghp_|gho_)\S+|[0-9a-f]{40}")
_REQUIRED_SCOPES = (
    ("repo", {"repo"}),
    ("read:org", {"read:org", "write:org", "admin:org"}),
)
TOKENS_PAGE = "https://github.com/settings/tokens"
# The failure code the UI turns into its own message; it never renders ours.
MISSING_SCOPES = "missing_scopes"

# gh failures that say nothing about the token itself.
_GH_INFRA_FAILURES = {GhErrorKind.NO_CLI, GhErrorKind.TIMEOUT, GhErrorKind.NETWORK}


def looks_like_token(token: str) -> bool:
    """Cheap client-side sanity check before spending a round-trip on GitHub."""
    return token.startswith(_TOKEN_PREFIXES) or len(token) >= _MIN_TOKEN_LENGTH


def missing_required_scopes(token: str, scopes: str) -> list[str]:
    """The scopes gh needs that this token lacks, given its X-OAuth-Scopes header.
    Empty for a fine-grained PAT, which has no scopes to check."""
    if not _SCOPED_TOKEN_RE.fullmatch(token):
        return []
    granted = {scope.strip() for scope in scopes.split(",")}
    return [name for name, satisfied_by in _REQUIRED_SCOPES if granted.isdisjoint(satisfied_by)]


def _missing_scopes_error(missing: list[str]) -> str:
    names = " and ".join(f"`{name}`" for name in missing)
    noun = "scope" if len(missing) == 1 else "scopes"
    return (f"This token is missing the {names} {noun} GitHub CLI needs. Edit it at "
            f"{TOKENS_PAGE}, tick {names}, and save the token again. A fine-grained token "
            "limited to the repositories HEARTH maintains needs no scopes and is preferred.")


async def connect(token: str, *, gh: GhCli | None = None) -> dict[str, Any]:
    """
    Validate a pasted PAT and, if it is good, hand it to gh's credential store.

    Returns:
        {"ok": True,  "payload": <connection body>}                  on success
        {"ok": False, "status": "needs_auth"|"failed", "error": ...}   otherwise,
        plus "code": "missing_scopes" and "missing_scopes": [...] when a classic
        token lacks the scopes gh needs
    """
    if not gh_available():
        return {
            "ok": False,
            "status": "failed",
            "error": "GitHub CLI (`gh`) is not installed, and it holds the token. "
                     "It ships in the space image; elsewhere install it from https://cli.github.com/.",
        }

    result = await validate_token(token)
    if not result.get("valid"):
        return {"ok": False, "status": result["status"], "error": result.get("error", "Validation failed.")}

    missing = missing_required_scopes(token, result.get("scopes", ""))
    if missing:
        return {
            "ok": False,
            "status": "needs_auth",
            "code": MISSING_SCOPES,
            "missing_scopes": missing,
            "error": _missing_scopes_error(missing),
        }

    gh = gh or GhCli()
    login = await gh.login_with_token(token)
    if not login.ok:
        if login.kind in _GH_INFRA_FAILURES:
            return {"ok": False, "status": "failed", "error": f"GitHub CLI could not sign in: {login.message or login.kind}"}
        reason = login.message or "`gh auth login` failed."
        return {"ok": False, "status": "needs_auth", "error": f"GitHub CLI rejected this token: {reason}"}

    # Only once gh has accepted the new token: a rejected replacement leaves the
    # current connection as it was.
    await sign_gh_out_of_other_accounts(gh)
    save_github_credential(result, auth_method=AUTH_METHOD)
    await configure_git_identity(result)
    log.info("GitHub connected as @%s (via PAT, held by gh)", result.get("username"))
    return {"ok": True, "payload": connection_payload(result, AUTH_METHOD)}
