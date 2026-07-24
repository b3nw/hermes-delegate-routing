"""The monkeypatch seams.

Three narrow wrappers over ``tools.delegate_tool`` module attributes (see
docs/DESIGN.md §6):

  A. schema  — advertise ``tasks[].model`` / ``tasks[].provider`` to the LLM
  B. capture — resolve per-task creds and stash them by task_index
  C. apply   — inject stashed creds into each ``_build_child_agent`` call

This module defines the wrapper *factories*; the orchestration that imports the
host, validates signatures, and installs them lives in ``apply_patches()``.
Only per-task ``tasks[]`` fields are supported — top-level
``model``/``provider`` never reach the tool (DESIGN §6.1).
"""

from __future__ import annotations

import copy
import inspect
import json
import logging
import threading

from ._state import ROUTING, get_creds
from .resolver import resolve_model_provider_override

logger = logging.getLogger(__name__)

# Serializes apply_patches() so a concurrent second caller can't pass the
# _HDR_PATCHED check before the first sets it (which would double-wrap).
_PATCH_LOCK = threading.Lock()

# Host function parameters we depend on. If a future hermes-agent drops/renames
# any of these, apply_patches() refuses to patch rather than half-wrap.
_EXPECTED_DELEGATE_PARAMS = {
    "goal", "context", "tasks", "max_iterations", "role", "background", "parent_agent",
}
_EXPECTED_BUILD_CHILD_PARAMS = {
    "task_index", "goal", "context", "toolsets", "model", "max_iterations",
    "task_count", "parent_agent", "override_provider", "override_base_url",
    "override_api_key", "override_api_mode", "override_acp_command",
    "override_acp_args", "role",
}


def _tool_error(msg: str, tool_error=None) -> str:
    """Return a host-shaped tool error string.

    Uses the host's ``tool_error`` when provided; otherwise a compatible
    ``{"error": ...}`` JSON string (the host's own error shape).
    """
    if tool_error is not None:
        try:
            return tool_error(msg)
        except Exception:  # pragma: no cover - defensive
            pass
    return json.dumps({"error": msg})

# --- Seam A: schema ---------------------------------------------------------

_TASK_MODEL_DESC = (
    "Per-task model override for this subagent. Accepts a model name or alias as "
    "used by /model (e.g. 'sonnet', 'gemini-flash-2.0'), optionally with an "
    "inline '--provider <id>'. Do NOT use provider:model syntax; set the separate "
    "'provider' field instead. When omitted, the child inherits the batch/config "
    "model."
)
_TASK_PROVIDER_DESC = (
    "Per-task provider override. When set, this subagent connects to the specified "
    "provider instead of inheriting from delegation.provider or the parent. The "
    "provider must be configured in Hermes. Prefer this structured field over "
    "embedding '--provider' in 'model' for JSON tool calls."
)


def make_schema_override(orig_builder):
    """Wrap ``_build_dynamic_schema_overrides`` to advertise tasks[].model/provider.

    Deep-copies the original output before injecting because the host builder only
    shallow-copies each property, leaving ``tasks.items`` aliased to the static
    schema — mutating it in place would corrupt the host's schema (DESIGN §6).
    """

    def _wrapped(*args, **kwargs):
        base = orig_builder(*args, **kwargs)
        if not isinstance(base, dict):
            return base
        result = copy.deepcopy(base)
        try:
            props = result["parameters"]["properties"]["tasks"]["items"]["properties"]
        except (KeyError, TypeError):
            logger.warning(
                "delegate-routing: unexpected delegate schema shape; "
                "not advertising model/provider fields"
            )
            return result
        props.setdefault("model", {"type": "string", "description": _TASK_MODEL_DESC})
        props.setdefault("provider", {"type": "string", "description": _TASK_PROVIDER_DESC})
        return result

    return _wrapped


# --- Seam B: capture --------------------------------------------------------

def make_delegate_task_wrapper(orig_delegate_task, resolver, on_error="fail", tool_error=None):
    """Wrap ``delegate_task`` to resolve per-task creds into ROUTING by index.

    Reads ``tasks[i].model`` / ``tasks[i].provider`` (top-level model/provider
    never reach the tool — DESIGN §6.1), resolves each via ``resolver`` and stashes
    the creds keyed by task index for the apply seam to consume. The original is
    then called unchanged; ROUTING is always reset afterwards.

    ``on_error``: 'fail' (default) → return a tool error and do not delegate;
    'fallback' → skip the failed override (child uses batch/config creds) and log.
    """

    def _wrapped(goal=None, context=None, tasks=None, max_iterations=None,
                 role=None, background=None, parent_agent=None, **extra):
        routing = {}
        if isinstance(tasks, list):
            for i, t in enumerate(tasks):
                if not isinstance(t, dict):
                    continue
                model = t.get("model")
                provider = t.get("provider")
                if not (model or provider):
                    continue
                try:
                    routing[i] = resolver(
                        model_input=model,
                        provider_input=provider,
                        parent_agent=parent_agent,
                    )
                except Exception as exc:
                    if on_error == "fallback":
                        logger.warning(
                            "delegate-routing: task %d override (model=%r provider=%r) "
                            "failed to resolve, using batch/config creds: %s",
                            i, model, provider, exc,
                        )
                        continue
                    return _tool_error(
                        f"delegate_task routing: could not resolve model/provider "
                        f"for task {i} (model={model!r}, provider={provider!r}): {exc}",
                        tool_error,
                    )
        token = ROUTING.set(routing)
        try:
            return orig_delegate_task(
                goal=goal, context=context, tasks=tasks,
                max_iterations=max_iterations, role=role,
                background=background, parent_agent=parent_agent, **extra,
            )
        finally:
            ROUTING.reset(token)

    return _wrapped


# --- Seam C: apply ----------------------------------------------------------

def make_build_child_wrapper(orig_build_child):
    """Wrap ``_build_child_agent`` to inject per-task creds keyed by task_index.

    Signature mirrors the host (DESIGN §6, seam C). ``task_index`` is the only
    correlation key the host passes, so routing is looked up by index. When a
    task has no override, the original batch/config creds pass through unchanged.
    """

    def _wrapped(task_index, goal, context, toolsets, model, max_iterations,
                 task_count, parent_agent, override_provider=None,
                 override_base_url=None, override_api_key=None,
                 override_api_mode=None, override_acp_command=None,
                 override_acp_args=None, role="leaf", **extra):
        creds = get_creds(task_index)
        if creds:
            model = creds.get("model") or model
            override_provider = creds.get("provider") or override_provider
            override_base_url = creds.get("base_url") or override_base_url
            override_api_key = creds.get("api_key") or override_api_key
            override_api_mode = creds.get("api_mode") or override_api_mode
            override_acp_command = creds.get("command") or override_acp_command
            override_acp_args = creds.get("args") or override_acp_args
        # Forward by keyword (not position) so a future host that inserts/appends
        # a parameter can't silently misalign creds.
        return orig_build_child(
            task_index=task_index, goal=goal, context=context, toolsets=toolsets,
            model=model, max_iterations=max_iterations, task_count=task_count,
            parent_agent=parent_agent, override_provider=override_provider,
            override_base_url=override_base_url, override_api_key=override_api_key,
            override_api_mode=override_api_mode,
            override_acp_command=override_acp_command,
            override_acp_args=override_acp_args, role=role, **extra,
        )

    return _wrapped


# --- Orchestration ----------------------------------------------------------

def _params(fn) -> set:
    return set(inspect.signature(fn).parameters)


def _read_on_error() -> str:
    """Read delegate_routing.on_error from host config; default 'fail'."""
    try:
        from hermes_cli.config import load_config

        cfg = load_config() or {}
        val = (cfg.get("delegate_routing") or {}).get("on_error") or "fail"
        return "fallback" if str(val).strip().lower() == "fallback" else "fail"
    except Exception:
        return "fail"


def _invalidate_tool_defs_cache(registry) -> None:
    """Force the host to recompute cached tool definitions after Seam A.

    ``model_tools.get_tool_definitions(quiet_mode=True)`` — the fast path the
    agent loop uses — memoizes into ``_tool_defs_cache`` keyed partly on
    ``registry._generation``. Assigning ``entry.dynamic_schema_overrides``
    directly does NOT bump ``_generation`` (only register/deregister do), so a
    long-running gateway that populated the memo with the stock schema BEFORE we
    patched keeps serving the field-less schema for the life of the process —
    the LLM never sees ``tasks[].model``/``.provider`` and can't route. Both
    hooks below are private host internals; each is best-effort and guarded so a
    future host that renames them just degrades to no invalidation.
    """
    try:
        registry._generation += 1
    except Exception:  # pragma: no cover - defensive; private attr may move
        logger.warning(
            "delegate-routing: could not bump registry._generation; a warm "
            "tool-definitions cache may keep serving the stock schema until "
            "the next registry mutation"
        )
    try:
        from model_tools import _clear_tool_defs_cache

        _clear_tool_defs_cache()
    except Exception:  # pragma: no cover - defensive; helper may move/rename
        pass


def _patch_schema(dt) -> None:
    """Seam A — wrap the registered ToolEntry's dynamic_schema_overrides.

    The registry stores a direct reference to the builder at registration time,
    so rebinding the module attribute would NOT reach it — we must update the
    ToolEntry itself.
    """
    try:
        from tools.registry import registry

        entry = registry.get_entry("delegate_task")
    except Exception as exc:
        logger.warning(
            "delegate-routing: registry unavailable; model/provider fields "
            "will not be advertised in the schema: %s", exc,
        )
        return
    if entry is None:
        logger.warning(
            "delegate-routing: delegate_task not in registry; schema fields "
            "not advertised"
        )
        return
    current = getattr(entry, "dynamic_schema_overrides", None) or getattr(
        dt, "_build_dynamic_schema_overrides", None
    )
    if not callable(current):
        logger.warning("delegate-routing: no schema builder to wrap; skipping Seam A")
        return
    entry.dynamic_schema_overrides = make_schema_override(current)
    # A direct attribute mutation doesn't bump registry._generation, so the
    # memoized tool-definitions cache won't refresh on its own — invalidate it.
    _invalidate_tool_defs_cache(registry)


def apply_patches() -> bool:
    """Install the three seams on the host, once. Returns True if active.

    Refuses to patch (returns False, no changes) if the host isn't importable or
    its function signatures don't match expectations — the plugin degrades to a
    no-op and core behavior is untouched. Idempotent via a module sentinel.
    """
    try:
        import tools.delegate_tool as dt
    except Exception as exc:
        logger.warning(
            "delegate-routing: host tools.delegate_tool not importable; "
            "plugin inactive: %s", exc,
        )
        return False

    with _PATCH_LOCK:
        if getattr(dt, "_HDR_PATCHED", False):
            return True

        try:
            dt_params = _params(dt.delegate_task)
            bc_params = _params(dt._build_child_agent)
        except Exception as exc:
            logger.warning(
                "delegate-routing: cannot introspect host functions; not patching: %s", exc,
            )
            return False

        schema_builder = getattr(dt, "_build_dynamic_schema_overrides", None)
        missing_dt = _EXPECTED_DELEGATE_PARAMS - dt_params
        missing_bc = _EXPECTED_BUILD_CHILD_PARAMS - bc_params
        if missing_dt or missing_bc or not callable(schema_builder):
            logger.warning(
                "delegate-routing: host signature mismatch — NOT patching. "
                "delegate_task missing=%s, _build_child_agent missing=%s, "
                "schema_builder=%r. This hermes-agent version may be unsupported; "
                "see docs/DESIGN.md §10.",
                sorted(missing_dt), sorted(missing_bc), schema_builder,
            )
            return False

        on_error = _read_on_error()
        tool_error = getattr(dt, "tool_error", None)

        # Seam B (capture) and Seam C (apply) via module-attribute rebind. Both
        # call sites resolve these as module globals at call time, so this reaches
        # every path including run_agent._dispatch_delegate_task (DESIGN §6.1).
        dt.delegate_task = make_delegate_task_wrapper(
            dt.delegate_task, resolve_model_provider_override,
            on_error=on_error, tool_error=tool_error,
        )
        dt._build_child_agent = make_build_child_wrapper(dt._build_child_agent)

        # Seam A (schema) via the ToolEntry.
        _patch_schema(dt)

        dt._HDR_PATCHED = True
        logger.info(
            "delegate-routing: active — patched delegate_task, _build_child_agent, "
            "and delegate schema (on_error=%s)", on_error,
        )
        return True
