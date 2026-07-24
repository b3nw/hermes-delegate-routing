"""Per-call routing state shared between the capture seam (B) and apply seam (C).

The capture wrapper on ``delegate_task`` resolves per-task creds and stashes them
here keyed by ``task_index``; the wrapper on ``_build_child_agent`` reads them
back by ``task_index`` (the only correlation key it receives). A ``ContextVar``
isolates concurrent/overlapping ``delegate_task`` calls (per thread / per async
task) and the build loop runs synchronously within one call's context, so the
index→creds map is stable for that call. See docs/DESIGN.md §6 (Seams B, C) and §9
(concurrency).
"""

from __future__ import annotations

import contextvars

# Maps task_index -> resolved creds dict (see resolver.resolve_model_provider_override).
# Default is None (not a shared mutable {}); the capture seam always .set()s a
# fresh dict per call, and get_creds() normalizes the unset case.
ROUTING: contextvars.ContextVar[dict[int, dict] | None] = contextvars.ContextVar(
    "hermes_delegate_routing", default=None
)


def get_creds(task_index: int) -> dict | None:
    """Return resolved creds for a task index, or None if not routed."""
    routing = ROUTING.get()
    if not routing:
        return None
    return routing.get(task_index)
