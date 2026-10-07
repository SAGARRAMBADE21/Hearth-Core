"""Claude Code's encoded-cwd transcript directory ↔ HEARTH job id helpers.

Claude Code writes each session log to
``<config>/projects/<encoded-cwd>/<sessionId>.jsonl``. Current CLIs encode the
working directory by replacing **every** non-alphanumeric character with ``-``
(and hash-suffixing very long paths), so the encoding is lossy: a decode cannot
tell ``job_1`` from ``job-1`` or ``/`` from ``.``.

These helpers never decode. The forward direction uses the SDK's own
``project_key_for_directory`` (the same realpath + sanitize the CLI uses), and the
reverse matches the encoded prefix against the real job directories under the
workspaces root, longest match first.

HEARTH runs every job in ``$HEARTH_STATE_DIR/workspaces/<job_id>/<step>``, so the
job id is the first path segment after the workspaces root.

Shape mirrors xo-space ``adapters/claude_code/_project_encoding.py`` (whose
``/``-only encoding predates the CLI's current sanitizer).
"""

from __future__ import annotations

import os
from pathlib import Path

from claude_agent_sdk import project_key_for_directory

from services.storage.layout import workspaces_dir


def projects_dir() -> Path:
    """Where the CLI keeps transcripts: ``CLAUDE_PROJECTS_DIR`` → ``$CLAUDE_CONFIG_DIR/projects`` → ``~/.claude/projects``."""
    configured = (os.getenv("CLAUDE_PROJECTS_DIR") or "").strip()
    if configured:
        return Path(configured).expanduser()
    config_dir = (os.getenv("CLAUDE_CONFIG_DIR") or "").strip()
    if config_dir:
        return Path(config_dir).expanduser() / "projects"
    return Path.home() / ".claude" / "projects"


def _encode_path(abs_path: str | Path) -> str:
    """Forward direction, exactly as the CLI names the folder. Never reversed."""
    return project_key_for_directory(str(abs_path))


def transcript_dir(directory: str | Path) -> Path:
    """The folder holding transcripts of sessions whose cwd was ``directory``."""
    return projects_dir() / _encode_path(directory)


def job_id_for_encoded_cwd(encoded: str) -> str | None:
    """Best-effort: encoded folder name → job id, by longest match against existing job directories.

    Returns ``None`` when the session did not run under the workspaces root, or its
    job directory is gone.
    """
    root = workspaces_dir()
    if not encoded or not root.is_dir():
        return None
    prefix = _encode_path(root) + "-"
    if not encoded.startswith(prefix):
        return None
    remainder = encoded[len(prefix):]
    if not remainder:
        return None
    try:
        jobs = [c.name for c in root.iterdir() if c.is_dir() and not c.name.startswith(".")]
    except OSError:
        return None
    # Compare in encoded form (job_1 → job-1), longest first, so "job-1" never shadows "job-1-revise".
    for name in sorted(jobs, key=len, reverse=True):
        enc = project_key_for_directory(str(root / name))[len(prefix):]
        if remainder == enc or remainder.startswith(enc + "-"):
            return name
    return None
