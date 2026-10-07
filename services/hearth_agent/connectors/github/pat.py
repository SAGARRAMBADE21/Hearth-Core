"""
GitHub connector — PAT (Personal Access Token) acquisition.

No OAuth app. The customer creates a fine-grained PAT (ideally on a dedicated
machine user such as ``hearth-bot``) limited to the repositories HEARTH should
maintain, with Contents, Pull requests, Issues and Commit statuses read/write and
Metadata read — never Administration — and pastes it into the HEARTH UI once.
This module validates it and hands it to gh (``gh auth login --with-token``);
only metadata is written to token.json (PRD §7 onboarding step 2).

Shape mirrors xo-space ``connectors/github/pat.py``.
"""

import logging
from typing import Any

from .common import (
    configure_git_identity,
    connection_payload,
    save_github_credential,
    validate_token,
)
from .gh_api import GhCli

log = logging.getLogger(__name__)

AUTH_METHOD = "pat"

# Prefixes GitHub uses for tokens a user can paste: classic PAT (ghp_),
# fine-grained PAT (github_pat_).
_TOKEN_PREFIXES = ("ghp_", "github_pat_")
_MIN_TOKEN_LENGTH = 30


def looks_like_token(token: str) -> bool:
    """Cheap client-side sanity check before spending a round-trip on GitHub."""
    return token.startswith(_TOKEN_PREFIXES) or len(token) >= _MIN_TOKEN_LENGTH


async def connect(token: str, *, gh: GhCli | None = None) -> dict[str, Any]:
    """
    Validate a pasted PAT and, if it is good, hand it to gh.

    Returns:
        {"ok": True,  "payload": <connection body>}                on success
        {"ok": False, "status": "needs_auth"|"failed", "error": ...} otherwise
    """
    result = await validate_token(token)
    if not result.get("valid"):
        return {"ok": False, "status": result["status"], "error": result.get("error", "Validation failed.")}

    gh = gh or GhCli()
    login = await gh.login_with_token(token)
    if not login.ok:
        return {"ok": False, "status": "failed", "error": f"gh auth login failed: {login.message or login.kind}"}

    save_github_credential(result, auth_method=AUTH_METHOD)
    await configure_git_identity(result)
    log.info("GitHub connected as @%s (via PAT, held by gh)", result.get("username"))
    return {"ok": True, "payload": connection_payload(result, AUTH_METHOD)}
