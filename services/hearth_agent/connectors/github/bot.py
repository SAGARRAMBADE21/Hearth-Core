"""``/hearth`` PR comment commands (TDD §9)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

Action = Literal["retry", "revise", "explain", "close"]

_CMD_RE = re.compile(r"^\s*/hearth\s+(retry|revise|explain|close)\b[ \t]*(.*)$", re.IGNORECASE | re.MULTILINE)


@dataclass(frozen=True)
class BotCommand:
    action: Action
    argument: str = ""


def parse_bot_command(body: str) -> BotCommand | None:
    """Return the first ``/hearth`` command in a comment body, or ``None``.

    Authorisation (org membership, not the bot's own account) is checked by the caller.
    """
    m = _CMD_RE.search(body or "")
    if not m:
        return None
    action = m.group(1).lower()
    arg = m.group(2).strip()
    if action == "revise" and not arg:
        return None
    return BotCommand(action, arg)  # type: ignore[arg-type]
