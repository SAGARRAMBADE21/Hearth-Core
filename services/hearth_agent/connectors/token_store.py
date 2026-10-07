"""
token_store — the single owner of token.json.

Every connector persists its credential entry as a provider-keyed object in one
shared JSON file at ``$HEARTH_STATE_DIR/secrets/token.json``. This module is the
ONLY place that knows the file's location, its on-disk shape, and its read/write
semantics. Connectors get/set/delete by provider key and never touch the format.

Writes are atomic (temp file + rename) so a crash never leaves a half-written
store, and the file is owner-only. ``HEARTH_TOKENS_FILE`` overrides the location.

Shape mirrors xo-space ``connectors/token_store.py``.
"""

import json
import logging
import os
from pathlib import Path
from typing import Any

from services.storage.layout import ensure_parent_dir, secrets_dir

log = logging.getLogger(__name__)

_FILE_MODE = 0o600


def token_file() -> Path:
    return Path(os.getenv("HEARTH_TOKENS_FILE") or secrets_dir() / "token.json").expanduser()


def read_all(*, read_only: bool = False) -> dict[str, Any]:
    """Read token.json. Read-only callers get an exception on a corrupt file instead of ``{}``,
    so a failed read cannot masquerade as "no credentials"."""
    path = token_file()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        if read_only:
            raise
        log.warning("Could not read %s: %s", path, exc)
        return {}
    if not isinstance(data, dict):
        if read_only:
            raise ValueError("Credential store must contain an object")
        return {}
    return data


def write_all(data: dict[str, Any]) -> None:
    """Write the full token.json atomically, pretty-printed, owner-only."""
    path = token_file()
    ensure_parent_dir(path)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    try:
        os.chmod(tmp, _FILE_MODE)
    except OSError as exc:  # e.g. a mount that ignores chmod
        log.warning("Could not restrict permissions on %s: %s", tmp, exc)
    os.replace(tmp, path)


def get_entry(provider: str, *, read_only: bool = False) -> dict[str, Any] | None:
    """Return the stored entry for a provider key, or None if absent."""
    entry = read_all(read_only=read_only).get(provider)
    if entry is not None and not isinstance(entry, dict):
        if read_only:
            raise ValueError("Credential entry must contain an object")
        return None
    return entry


def set_entry(provider: str, entry: dict[str, Any]) -> None:
    """Insert or replace one provider's entry, preserving every other key."""
    data = read_all()
    data[provider] = entry
    write_all(data)


def delete_entry(provider: str) -> None:
    """Remove one provider's entry if present, preserving every other key."""
    data = read_all()
    if data.pop(provider, None) is not None:
        write_all(data)
