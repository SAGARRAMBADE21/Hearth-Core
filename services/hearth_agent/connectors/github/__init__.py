"""
GitHub connector.

Two ways to acquire a credential, one shared everything-else, and the job surface:

  * ``pat``      — the customer pastes a fine-grained personal access token
  * ``cli_auth`` — the `gh auth login` device flow
  * ``common``   — metadata storage, validation, status, git identity
  * ``gh_api``   — typed, classified ``gh api`` client (PRs, statuses, issues, ETags)
  * ``repo``     — bare mirror, credential-free tree export into sandboxes, patch + push
  * ``pulls``    — branch naming and PR body rendering
  * ``poller``   — ETag / since-cursor polling (the space accepts no webhooks)
  * ``bot``      — ``/hearth`` PR comment commands

Callers import from this package and stay unaware of the module split.
"""

from . import cli_auth, pat
from .bot import BotCommand, parse_bot_command
from .common import (
    GITHUB_API,
    AuthMethod,
    GitHubStatus,
    commit_email,
    configure_git_identity,
    connection_payload,
    disconnect_github_account,
    expiry_warning,
    get_github_auth_method,
    get_github_credential,
    get_github_token,
    get_status,
    gh_available,
    save_github_credential,
    sign_gh_out,
    sign_gh_out_of_other_accounts,
    validate_token,
)
from .gh_api import AuthStatus, GhAccount, GhCli, GhErrorKind, GhResult, RateLimit
from .poller import PollCursor, PollOutcome, poll_default_branch, poll_pr_comments
from .pulls import Branding, PullRequestContent, branch_name, render_pr
from .repo import GitError, RepoMirror

__all__ = [
    "GITHUB_API",
    "AuthMethod",
    "AuthStatus",
    "BotCommand",
    "Branding",
    "GhAccount",
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
    "cli_auth",
    "commit_email",
    "configure_git_identity",
    "connection_payload",
    "disconnect_github_account",
    "expiry_warning",
    "get_github_auth_method",
    "get_github_credential",
    "get_github_token",
    "get_status",
    "gh_available",
    "parse_bot_command",
    "pat",
    "poll_default_branch",
    "poll_pr_comments",
    "render_pr",
    "save_github_credential",
    "sign_gh_out",
    "sign_gh_out_of_other_accounts",
    "validate_token",
]
