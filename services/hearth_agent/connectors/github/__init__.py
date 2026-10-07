"""
GitHub connector.

One way to acquire a credential, one shared everything-else, and the job surface:

  * ``pat``      — the customer pastes a fine-grained personal access token
  * ``common``   — metadata storage, validation, status, git identity
  * ``gh_api``   — typed, classified ``gh api`` client (PRs, statuses, issues, ETags)
  * ``repo``     — bare mirror, credential-free tree export into sandboxes, patch + push
  * ``pulls``    — branch naming and PR body rendering
  * ``poller``   — ETag / since-cursor polling (the space accepts no webhooks)
  * ``bot``      — ``/hearth`` PR comment commands

Callers import from this package and stay unaware of the module split.
"""

from . import pat
from .bot import BotCommand, parse_bot_command
from .common import (
    GITHUB_API,
    AuthMethod,
    GitHubStatus,
    commit_email,
    configure_git_identity,
    connection_payload,
    delete_github_credential,
    expiry_warning,
    get_github_auth_method,
    get_github_credential,
    get_github_token,
    get_status,
    save_github_credential,
    validate_token,
)
from .gh_api import AuthStatus, GhCli, GhErrorKind, GhResult, RateLimit
from .poller import PollCursor, PollOutcome, poll_default_branch, poll_pr_comments
from .pulls import Branding, PullRequestContent, branch_name, render_pr
from .repo import GitError, RepoMirror

__all__ = [
    "GITHUB_API",
    "AuthMethod",
    "AuthStatus",
    "BotCommand",
    "Branding",
    "GhCli",
    "GhErrorKind",
    "GhResult",
    "GitError",
    "GitHubStatus",
    "PollCursor",
    "PollOutcome",
    "PullRequestContent",
    "RateLimit",
    "RepoMirror",
    "branch_name",
    "commit_email",
    "configure_git_identity",
    "connection_payload",
    "delete_github_credential",
    "expiry_warning",
    "get_github_auth_method",
    "get_github_credential",
    "get_github_token",
    "get_status",
    "parse_bot_command",
    "pat",
    "poll_default_branch",
    "poll_pr_comments",
    "render_pr",
    "save_github_credential",
    "validate_token",
]
