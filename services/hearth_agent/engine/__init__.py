"""
The agent engine — agent-agnostic runtime that turns a remediation job into
normalized events.

- dispatcher    : routes a job to the active agent's adapter
- stream_events : the event vocabulary every adapter's ``stream()`` speaks

None of these name a specific agent; they resolve behavior via the adapters
capability loader.
"""
