"""Tests for Seams B (capture) and C (apply), composed as they run in the host.

The host's delegate_task loop calls the module-global _build_child_agent for each
task with task_index=i and batch-wide creds. We simulate that: a fake
orig_delegate_task iterates tasks and calls the WRAPPED build-child (mirroring the
host resolving the patched module attr), so capture+apply are exercised together.
"""

from __future__ import annotations

import json

from hermes_delegate_routing import _state
from hermes_delegate_routing.patches import (
    make_build_child_wrapper,
    make_delegate_task_wrapper,
)

BATCH_MODEL = "BATCH_MODEL"
BATCH_PROVIDER = "BATCH_PROVIDER"


def _fake_resolver(model_input=None, provider_input=None, parent_agent=None):
    return {
        "model": f"resolved-{model_input}" if model_input else None,
        "provider": provider_input,
        "base_url": None,
        "api_key": None,
        "api_mode": None,
        "command": None,
        "args": [],
    }


def _raising_resolver(model_input=None, provider_input=None, parent_agent=None):
    raise ValueError("boom")


def _make_host(build_child, seen_routing=None):
    """Return a fake orig_delegate_task mimicking the host build loop."""

    def _orig_delegate_task(goal=None, context=None, tasks=None, max_iterations=None,
                            role=None, background=None, parent_agent=None):
        if seen_routing is not None:
            seen_routing.append(dict(_state.ROUTING.get()))
        for i, t in enumerate(tasks or []):
            build_child(
                i, t["goal"], t.get("context"), None, BATCH_MODEL, 10, len(tasks),
                parent_agent, override_provider=BATCH_PROVIDER, role="leaf",
            )
        return "ok"

    return _orig_delegate_task


def _spy_build_child():
    calls = []

    def _orig_build_child(task_index, goal, context, toolsets, model, max_iterations,
                          task_count, parent_agent, override_provider=None,
                          override_base_url=None, override_api_key=None,
                          override_api_mode=None, override_acp_command=None,
                          override_acp_args=None, role="leaf"):
        calls.append({"i": task_index, "model": model, "provider": override_provider})
        return ("child", task_index)

    return _orig_build_child, calls


def test_per_task_override_routes_by_index():
    orig_build, calls = _spy_build_child()
    wrapped_build = make_build_child_wrapper(orig_build)
    host = _make_host(wrapped_build)
    wrapped_delegate = make_delegate_task_wrapper(host, _fake_resolver, on_error="fail")

    wrapped_delegate(tasks=[
        {"goal": "a", "model": "m1", "provider": "p1"},
        {"goal": "b"},  # no override
    ], parent_agent=None)

    assert calls[0] == {"i": 0, "model": "resolved-m1", "provider": "p1"}
    assert calls[1] == {"i": 1, "model": BATCH_MODEL, "provider": BATCH_PROVIDER}


def test_index_alignment_three_tasks():
    orig_build, calls = _spy_build_child()
    wrapped_build = make_build_child_wrapper(orig_build)
    host = _make_host(wrapped_build)
    wrapped_delegate = make_delegate_task_wrapper(host, _fake_resolver, on_error="fail")

    wrapped_delegate(tasks=[
        {"goal": "0"},
        {"goal": "1", "model": "only-one"},
        {"goal": "2"},
    ], parent_agent=None)

    assert calls[0]["model"] == BATCH_MODEL
    assert calls[1]["model"] == "resolved-only-one"
    assert calls[2]["model"] == BATCH_MODEL


def test_routing_visible_during_call_and_reset_after():
    orig_build, _ = _spy_build_child()
    wrapped_build = make_build_child_wrapper(orig_build)
    seen = []
    host = _make_host(wrapped_build, seen_routing=seen)
    wrapped_delegate = make_delegate_task_wrapper(host, _fake_resolver, on_error="fail")

    wrapped_delegate(tasks=[{"goal": "a", "model": "m1"}], parent_agent=None)

    assert seen[0].get(0) is not None  # visible inside the call
    assert not _state.ROUTING.get()  # reset after


def test_fail_hard_returns_tool_error_and_skips_delegation():
    called = {"host": False}

    def host(**kw):
        called["host"] = True
        return "ok"

    wrapped_delegate = make_delegate_task_wrapper(host, _raising_resolver, on_error="fail")
    out = wrapped_delegate(tasks=[{"goal": "a", "model": "bad"}], parent_agent=None)

    assert called["host"] is False
    assert "error" in json.loads(out)
    assert not _state.ROUTING.get()  # not set on the fail path


def test_fallback_uses_batch_creds_and_still_delegates():
    orig_build, calls = _spy_build_child()
    wrapped_build = make_build_child_wrapper(orig_build)
    host = _make_host(wrapped_build)
    wrapped_delegate = make_delegate_task_wrapper(host, _raising_resolver, on_error="fallback")

    out = wrapped_delegate(tasks=[{"goal": "a", "model": "bad"}], parent_agent=None)

    assert out == "ok"
    assert calls[0]["model"] == BATCH_MODEL  # fell back to batch creds
    assert calls[0]["provider"] == BATCH_PROVIDER


def test_routing_reset_even_if_host_raises():
    def host(**kw):
        raise RuntimeError("host blew up")

    wrapped_delegate = make_delegate_task_wrapper(host, _fake_resolver, on_error="fail")
    try:
        wrapped_delegate(tasks=[{"goal": "a", "model": "m1"}], parent_agent=None)
    except RuntimeError:
        pass
    assert not _state.ROUTING.get()


def test_build_child_wrapper_forwards_unknown_future_kwarg():
    """Forward-compat: if a future host adds a kwarg to _build_child_agent, the
    apply wrapper must forward it, not raise TypeError."""
    seen = {}

    def orig_build_child(task_index, goal, context, toolsets, model, max_iterations,
                         task_count, parent_agent, override_provider=None,
                         override_base_url=None, override_api_key=None,
                         override_api_mode=None, override_acp_command=None,
                         override_acp_args=None, role="leaf", future_flag=None):
        seen["future_flag"] = future_flag
        return "ok"

    wrapped = make_build_child_wrapper(orig_build_child)
    out = wrapped(0, "g", None, None, "m", 10, 1, None,
                  override_provider="p", future_flag="NEW")
    assert out == "ok"
    assert seen["future_flag"] == "NEW"


def test_delegate_task_wrapper_forwards_unknown_future_kwarg():
    """Forward-compat: if a future host adds a kwarg to delegate_task, the capture
    wrapper must forward it."""
    seen = {}

    def orig_delegate_task(goal=None, context=None, tasks=None, max_iterations=None,
                           role=None, background=None, parent_agent=None, future_flag=None):
        seen["future_flag"] = future_flag
        return "ok"

    wrapped = make_delegate_task_wrapper(orig_delegate_task, _fake_resolver, on_error="fail")
    out = wrapped(goal="g", tasks=None, parent_agent=None, future_flag="NEW")
    assert out == "ok"
    assert seen["future_flag"] == "NEW"


def test_single_goal_no_tasks_is_passthrough():
    seen = []

    def host(goal=None, context=None, tasks=None, **kw):
        seen.append((goal, tasks))
        return "ok"

    wrapped_delegate = make_delegate_task_wrapper(host, _fake_resolver, on_error="fail")
    out = wrapped_delegate(goal="solo", tasks=None, parent_agent=None)
    assert out == "ok"
    assert seen == [("solo", None)]
