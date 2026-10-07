"""Tool-layer policy the agent adapter enforces (TDD §3 item 6, §6 "Agent guardrails").

This is the first line of defense: it runs in code before a tool executes (for Claude Code, in a
PreToolUse hook). The sandbox's network rule and unprivileged user are the second line; neither trusts
the agent.
"""

from __future__ import annotations

import fnmatch
import shlex
from dataclasses import dataclass, field
from pathlib import PurePosixPath

# Edits never allowed, whatever the job's scope.
ALWAYS_DENIED_PATHS = [
    ".github/workflows/**",
    ".gitlab-ci.yml",
    ".circleci/**",
    "**/.env",
    "**/.env.*",
    "**/*.pem",
    "**/*.key",
    "**/id_rsa*",
    ".git/**",
    ".hearth.yml",
]

TEST_PATH_GLOBS = [
    "**/test/**",
    "**/tests/**",
    "**/__tests__/**",
    "**/*.test.*",
    "**/*.spec.*",
    "**/test_*.py",
    "**/*_test.py",
]

# Binaries the agent may never run (network tools, VCS remotes, privilege changes).
DENIED_BINARIES = {
    "curl", "wget", "nc", "ncat", "netcat", "ssh", "scp", "sftp", "rsync", "ftp", "telnet",
    "sudo", "su", "doas", "chmod", "chown", "docker", "podman", "kubectl", "gh",
}
DENIED_GIT_SUBCOMMANDS = {"push", "remote", "fetch", "pull", "clone", "config", "credential", "submodule"}

DEFAULT_ALLOWED_BINARIES = {
    # package managers / runtimes
    "node", "npm", "npx", "pnpm", "yarn", "bun", "tsc", "python", "python3", "pip", "uv", "poetry",
    "pytest", "jest", "vitest", "eslint", "prettier", "ruff", "mypy", "pyright",
    # read-only shell helpers
    "ls", "cat", "head", "tail", "wc", "grep", "rg", "find", "sed", "awk", "diff", "echo", "pwd", "true",
    "ast-grep", "sg", "git",
}


@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason: str = ""

    @classmethod
    def allow(cls) -> Decision:
        return cls(True)

    @classmethod
    def deny(cls, reason: str) -> Decision:
        return cls(False, reason)


def _norm(path: str) -> str:
    p = PurePosixPath(path.replace("\\", "/"))
    if p.is_absolute() or ".." in p.parts:
        return ""
    return str(p)


def _match(path: str, globs: list[str]) -> bool:
    # fnmatch's "*" already crosses "/", so "**/x" also needs a root-level check.
    return any(fnmatch.fnmatch(path, g) or (g.startswith("**/") and fnmatch.fnmatch(path, g[3:])) for g in globs)


@dataclass
class ToolPolicy:
    allowed_edit_paths: list[str] = field(default_factory=list)  # globs, relative to the workspace root
    allow_test_edits: bool = True
    allowed_binaries: set[str] = field(default_factory=lambda: set(DEFAULT_ALLOWED_BINARIES))
    max_diff_lines: int = 1000

    @classmethod
    def for_files(cls, files: list[str], extra: list[str] | None = None) -> ToolPolicy:
        return cls(allowed_edit_paths=[*files, *(extra or [])])

    def check_edit(self, path: str, *, workspace_root: str | None = None) -> Decision:
        if workspace_root:
            root = workspace_root.replace("\\", "/").rstrip("/") + "/"
            p = path.replace("\\", "/")
            if p.startswith(root):
                path = p[len(root):]
        rel = _norm(path)
        if not rel:
            return Decision.deny(f"path escapes the workspace: {path}")
        if _match(rel, ALWAYS_DENIED_PATHS):
            return Decision.deny(f"edits to {rel} are never allowed (CI config, secrets, git internals)")
        if not self.allowed_edit_paths:
            return Decision.allow()
        if _match(rel, self.allowed_edit_paths):
            return Decision.allow()
        if self.allow_test_edits and _match(rel, TEST_PATH_GLOBS):
            return Decision.allow()
        return Decision.deny(f"{rel} is outside the Impact Report scope")

    def check_command(self, command: str | list[str]) -> Decision:
        try:
            argv = shlex.split(command) if isinstance(command, str) else list(command)
        except ValueError as e:
            return Decision.deny(f"unparseable command: {e}")
        if not argv:
            return Decision.deny("empty command")
        # Each segment of a pipeline / chain is checked on its own.
        segment: list[str] = []
        for tok in [*argv, "&&"]:
            if tok in {"&&", "||", ";", "|"}:
                if segment:
                    d = self._check_segment(segment)
                    if not d.allowed:
                        return d
                segment = []
            elif any(ch in tok for ch in ("`", "$(", ">", "<", ";", "|", "&", "\n")):
                return Decision.deny(f"shell substitution / redirection / chaining not allowed: {tok!r}")
            else:
                segment.append(tok)
        return Decision.allow()

    def _check_segment(self, argv: list[str]) -> Decision:
        # skip leading VAR=value assignments
        while argv and "=" in argv[0] and not argv[0].startswith("-"):
            argv = argv[1:]
        if not argv:
            return Decision.allow()
        binary = PurePosixPath(argv[0]).name
        if binary in DENIED_BINARIES:
            return Decision.deny(f"{binary} is blocked in the sandbox")
        if binary == "git":
            sub = next((a for a in argv[1:] if not a.startswith("-")), "")
            if sub in DENIED_GIT_SUBCOMMANDS:
                return Decision.deny(f"git {sub} is blocked; the PR Service owns all remote operations")
        if binary in {"npm", "pnpm", "yarn", "bun"} and len(argv) > 1 and argv[1] in {"publish", "login", "adduser"}:
            return Decision.deny(f"{binary} {argv[1]} is blocked")
        if binary not in self.allowed_binaries:
            return Decision.deny(f"{binary} is not on the command allowlist")
        return Decision.allow()
