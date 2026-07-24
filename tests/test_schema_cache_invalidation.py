"""Regression tests for the Seam A tool-definitions cache invalidation.

Bug (v0.1.1): Seam A advertised tasks[].model/provider by assigning
``entry.dynamic_schema_overrides`` directly, which does NOT bump
``registry._generation``. The host's ``model_tools.get_tool_definitions``
memoizes on that generation, so a long-running gateway that cached the stock
delegate_task schema BEFORE the plugin patched kept serving the field-less
schema — the LLM never saw model/provider and couldn't route. See
docs/DESIGN.md and MEMORY (delegate-routing-schema-cache-bug).

These tests pin the fix: ``_patch_schema`` must invalidate the cache
(bump ``_generation`` and clear ``_tool_defs_cache``) after wrapping the entry.
"""

from __future__ import annotations

import sys
import types


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


def _task_props(entry):
    schema = entry.dynamic_schema_overrides()
    return schema["parameters"]["properties"]["tasks"]["items"]["properties"]


def _install_fake_registry_and_model_tools(monkeypatch, *, with_generation=True,
                                           with_model_tools=True):
    """Inject a fake tools.registry (+ optional model_tools) that mimic the host
    memoization contract, and return (registry, entry, cache)."""

    def _build_dynamic_schema_overrides():
        return _host_schema()

    class _Entry:
        def __init__(self, builder):
            self.dynamic_schema_overrides = builder

    class _Registry:
        def __init__(self, entry):
            self._entry = entry
            if with_generation:
                self._generation = 41  # arbitrary non-zero starting point

        def get_entry(self, name):
            return self._entry if name == "delegate_task" else None

    entry = _Entry(_build_dynamic_schema_overrides)
    reg = _Registry(entry)

    reg_mod = types.ModuleType("tools.registry")
    reg_mod.registry = reg
    tools_pkg = types.ModuleType("tools")
    tools_pkg.__path__ = []
    monkeypatch.setitem(sys.modules, "tools", tools_pkg)
    monkeypatch.setitem(sys.modules, "tools.registry", reg_mod)

    cache = {("stock",): ["stale"]}  # stands in for a warm _tool_defs_cache
    if with_model_tools:
        mt = types.ModuleType("model_tools")

        def _clear_tool_defs_cache():
            cache.clear()

        mt._clear_tool_defs_cache = _clear_tool_defs_cache
        monkeypatch.setitem(sys.modules, "model_tools", mt)
    else:
        monkeypatch.setitem(sys.modules, "model_tools", None)  # -> ImportError

    # A fake host module for the dt arg (only used for the fallback builder).
    dt = types.ModuleType("tools.delegate_tool")
    dt._build_dynamic_schema_overrides = _build_dynamic_schema_overrides

    return reg, entry, cache, dt


def test_patch_schema_bumps_generation_and_clears_cache(monkeypatch):
    from hermes_delegate_routing.patches import _patch_schema

    reg, entry, cache, dt = _install_fake_registry_and_model_tools(monkeypatch)
    gen_before = reg._generation

    _patch_schema(dt)

    # Seam A still advertises the fields...
    props = _task_props(entry)
    assert "model" in props and "provider" in props
    # ...and the cache is invalidated so a warm gateway recomputes.
    assert reg._generation == gen_before + 1
    assert cache == {}  # _clear_tool_defs_cache() ran


def test_invalidation_survives_missing_generation(monkeypatch):
    """A host without registry._generation must not break patching."""
    from hermes_delegate_routing.patches import _patch_schema

    _, entry, cache, dt = _install_fake_registry_and_model_tools(
        monkeypatch, with_generation=False
    )

    _patch_schema(dt)  # must not raise

    props = _task_props(entry)
    assert "model" in props and "provider" in props
    # model_tools fallback still clears the cache.
    assert cache == {}


def test_invalidation_survives_missing_model_tools(monkeypatch):
    """A host without model_tools._clear_tool_defs_cache still bumps generation."""
    from hermes_delegate_routing.patches import _patch_schema

    reg, entry, _cache, dt = _install_fake_registry_and_model_tools(
        monkeypatch, with_model_tools=False
    )
    gen_before = reg._generation

    _patch_schema(dt)  # must not raise

    assert reg._generation == gen_before + 1
    props = _task_props(entry)
    assert "model" in props and "provider" in props
