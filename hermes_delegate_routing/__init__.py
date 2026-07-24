"""hermes-delegate-routing — explicit per-task model/provider routing for delegate_task.

A fork-free Hermes Agent plugin. It lets a batch delegation route each subagent
to a different model/provider via per-task fields:

    delegate_task(tasks=[
        {"goal": "cheap summarize", "model": "gemini-flash-2.0", "provider": "openrouter"},
        {"goal": "careful review",  "model": "sonnet",           "provider": "anthropic"},
    ])

Design and rationale live in docs/DESIGN.md. In short: `delegate_task` is
special-cased in the host runtime to bypass the tool registry, so the sanctioned
`register_tool(override=True)` path cannot intercept it. This plugin instead
applies three narrow, idempotent monkeypatches to `tools.delegate_tool` at load
time (schema advertise → capture per-task creds → apply per child). See
docs/DESIGN.md §6 and §6.1.

Only per-task `tasks[i].model`/`.provider` is supported (top-level is dropped by
the host before it reaches the tool). This matches upstream's own recommended
call shape.
"""

from __future__ import annotations

import logging

__version__ = "0.1.2"

logger = logging.getLogger(__name__)


def register(ctx=None) -> None:
    """Plugin entry point — called once at startup by the Hermes plugin loader.

    Installs the three monkeypatch seams on ``tools.delegate_tool`` (schema,
    capture, apply). Safe to call without a live ``ctx``. Never raises: if the
    host is missing or its signatures don't match, the plugin degrades to a
    no-op and logs a warning (see ``patches.apply_patches``).
    """
    from .patches import apply_patches

    try:
        active = apply_patches()
    except Exception:  # pragma: no cover - defensive; must never break startup
        logger.exception("hermes-delegate-routing: unexpected error during patch")
        return
    if active:
        logger.info("hermes-delegate-routing v%s active", __version__)
    else:
        logger.warning(
            "hermes-delegate-routing v%s loaded but INACTIVE (host unavailable "
            "or unsupported signature)", __version__,
        )
