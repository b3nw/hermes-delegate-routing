"""Tests for apply_patches orchestration.

Injects a fake ``tools.delegate_tool`` and ``tools.registry`` into sys.modules so
apply_patches() can run without a real host. Covers: patches applied once,
idempotency, schema wired via the ToolEntry, and signature-mismatch degradation.
"""

from __future__ import annotations

import sys
import types

import pytest


def _host_schema():
    return {
        "description": "Spawn subagents.",
        "parameters": {
            "type": "object",
            "properties": {
                "goal": {"type": "string"},
                "tasks": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {"goal": {"type": "string"}},
                    },
                },
            },
        },
    }


def _make_fake_host(*, bc_full=True):
    """Build fake tools.delegate_tool + tools.registry modules."""

    def delegate_task(goal=None, context=None, tasks=None, max_iterations=None,
                      role=None, background=None, parent_agent=None):
        return "orig"

    if bc_full:
        def _build_child_agent(task_index, goal, context, toolsets, model,
                               max_iterations, task_count, parent_agent,
                               override_provider=None, override_base_url=None,
                               override_api_key=None, override_api_mode=None,
                               override_acp_command=None, override_acp_args=None,
                               role="leaf"):
            return ("child", task_index, model, override_provider)
    else:  # missing override_provider -> signature mismatch
        def _build_child_agent(task_index, goal, context, toolsets, model,
                               max_iterations, task_count, parent_agent,
                               role="leaf"):
            return ("child", task_index)

    def _build_dynamic_schema_overrides():
        return _host_schema()

    def tool_error(msg):
        import json
        return json.dumps({"error": msg})

    dt = types.ModuleType("tools.delegate_tool")
    dt.delegate_task = delegate_task
    dt._build_child_agent = _build_child_agent
    dt._build_dynamic_schema_overrides = _build_dynamic_schema_overrides
    dt.tool_error = tool_error

    class _Entry:
        def __init__(self, builder):
            self.dynamic_schema_overrides = builder

    class _Registry:
        def __init__(self, entry):
            self._entry = entry

        def get_entry(self, name):
            return self._entry if name == "delegate_task" else None

    entry = _Entry(_build_dynamic_schema_overrides)
    reg_mod = types.ModuleType("tools.registry")
    reg_mod.registry = _Registry(entry)

    tools_pkg = types.ModuleType("tools")
    tools_pkg.__path__ = []

    return tools_pkg, dt, reg_mod, entry


@pytest.fixture
def fake_host(monkeypatch):
    def _install(*, bc_full=True):
        tools_pkg, dt, reg_mod, entry = _make_fake_host(bc_full=bc_full)
        monkeypatch.setitem(sys.modules, "tools", tools_pkg)
        monkeypatch.setitem(sys.modules, "tools.delegate_tool", dt)
        monkeypatch.setitem(sys.modules, "tools.registry", reg_mod)
        return dt, entry

    return _install


def test_applies_all_three_seams(fake_host):
    from hermes_delegate_routing.patches import apply_patches

    dt, entry = fake_host()
    orig_delegate = dt.delegate_task
    orig_build = dt._build_child_agent

    assert apply_patches() is True
    assert dt._HDR_PATCHED is True
    assert dt.delegate_task is not orig_delegate       # Seam B wrapped
    assert dt._build_child_agent is not orig_build      # Seam C wrapped

    # Seam A: the ToolEntry builder now advertises model/provider.
    schema = entry.dynamic_schema_overrides()
    props = schema["parameters"]["properties"]["tasks"]["items"]["properties"]
    assert "model" in props and "provider" in props


def test_idempotent(fake_host):
    from hermes_delegate_routing.patches import apply_patches

    dt, _ = fake_host()
    assert apply_patches() is True
    wrapped_once = dt.delegate_task
    assert apply_patches() is True          # second call no-ops
    assert dt.delegate_task is wrapped_once  # not re-wrapped


def test_signature_mismatch_degrades(fake_host):
    from hermes_delegate_routing.patches import apply_patches

    dt, _ = fake_host(bc_full=False)
    orig_delegate = dt.delegate_task

    assert apply_patches() is False          # refused
    assert dt.delegate_task is orig_delegate  # untouched
    assert getattr(dt, "_HDR_PATCHED", False) is False


def test_host_missing_is_noop(monkeypatch):
    from hermes_delegate_routing.patches import apply_patches

    # Make tools.delegate_tool import fail.
    monkeypatch.setitem(sys.modules, "tools", types.ModuleType("tools"))
    monkeypatch.setitem(sys.modules, "tools.delegate_tool", None)  # -> ImportError
    assert apply_patches() is False


def test_end_to_end_routing_through_patched_host(fake_host):
    """After patching, calling the patched delegate_task should route a per-task
    override through the patched _build_child_agent (simulating the host loop)."""
    from unittest.mock import patch as mock_patch

    from hermes_delegate_routing.patches import apply_patches

    dt, _ = fake_host()

    # Replace the host's build loop: make orig delegate_task call the (patched)
    # module-global _build_child_agent, as the real host does.
    calls = []

    def looping_delegate(goal=None, context=None, tasks=None, max_iterations=None,
                         role=None, background=None, parent_agent=None):
        for i, t in enumerate(tasks or []):
            r = dt._build_child_agent(i, t["goal"], None, None, "BATCH", 10,
                                      len(tasks), parent_agent,
                                      override_provider="BATCHP", role="leaf")
            calls.append(r)
        return "ok"

    dt.delegate_task = looping_delegate  # pre-patch original = our looping host
    dt.__dict__.pop("_HDR_PATCHED", None)

    with mock_patch(
        "hermes_cli.model_switch.switch_model",
    ) as mock_switch, mock_patch(
        "hermes_cli.runtime_provider.resolve_runtime_provider",
        return_value={"command": None, "args": []},
    ):
        from types import SimpleNamespace
        mock_switch.return_value = SimpleNamespace(
            success=True, new_model="ROUTED", target_provider="ROUTEDP",
            base_url=None, api_key=None, api_mode=None, error_message=None,
        )
        assert apply_patches() is True
        dt.delegate_task(tasks=[{"goal": "a", "model": "m1", "provider": "p1"},
                                {"goal": "b"}], parent_agent=None)

    # task 0 routed, task 1 batch
    assert calls[0] == ("child", 0, "ROUTED", "ROUTEDP")
    assert calls[1] == ("child", 1, "BATCH", "BATCHP")
