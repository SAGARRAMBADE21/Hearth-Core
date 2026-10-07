"""Claude Code visualizer source — not supported in HEARTH.

xo-space tails ``~/.claude/projects/*.jsonl`` into its live workspace
visualizer. HEARTH has no visualizer: a job's live view is the adapter's own
event stream (``engine/stream_events``, written to the job's ``events.jsonl``),
which the UI reads through the Engine API while someone watches. The ``Source``
class keeps xo-space's loader contract and simply yields nothing.

Shape mirrors xo-space ``adapters/claude_code/visualizer_source.py``.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

SUPPORTED = False
REASON = "HEARTH streams job events from the adapter (engine/stream_events); there is no visualizer."


class Source:
    """Loader contract: ``Source().poll_events()`` and ``Source().poll_presence()``."""

    supported = SUPPORTED

    def __init__(self, offsets: Any = None) -> None:
        self.offsets = offsets

    def poll_events(self) -> Iterator[Any]:
        return iter(())

    def poll_presence(self) -> list[dict]:
        return []
