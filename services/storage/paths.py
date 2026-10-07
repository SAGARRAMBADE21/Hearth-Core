"""Where HEARTH keeps machine-local state.

Default ``~/.hearth/``. Inside a space the Compose file points ``HEARTH_STATE_DIR``
at the space volume (``/var/lib/hearth``) so state survives container upgrades.
"""

from __future__ import annotations

import os
from pathlib import Path


def hearth_state_dir() -> Path:
    return Path(os.environ.get("HEARTH_STATE_DIR") or Path.home() / ".hearth").expanduser()
