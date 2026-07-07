"""Tests for Seam A — schema advertising tasks[].model/provider."""

from __future__ import annotations

from hermes_delegate_routing.patches import make_schema_override


def _host_like_builder_output():
    """Mimic the host's _build_dynamic_schema_overrides() return shape, including
    the shared-reference gotcha: tasks.items is a nested dict that, in the host,
    aliases the static schema."""
    return {
        "description": "Spawn subagents.",
        "parameters": {
            "type": "object",
            "properties": {
                "goal": {"type": "string", "description": "..."},
                "context": {"type": "string", "description": "..."},
                "role": {"type": "string", "description": "..."},
                "tasks": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "goal": {"type": "string", "description": "Task goal"},
                            "context": {"type": "string", "description": "..."},
                            "role": {"type": "string", "enum": ["leaf", "orchestrator"]},
                        },
                    },
                },
            },
        },
    }


def test_injects_model_and_provider_into_tasks_items():
    static = _host_like_builder_output()
    wrapped = make_schema_override(lambda: static)
    out = wrapped()
    task_props = out["parameters"]["properties"]["tasks"]["items"]["properties"]
    assert "model" in task_props and task_props["model"]["type"] == "string"
    assert "provider" in task_props and task_props["provider"]["type"] == "string"


def test_does_not_touch_top_level_properties():
    wrapped = make_schema_override(_host_like_builder_output)
    out = wrapped()
    top = out["parameters"]["properties"]
    assert "model" not in top
    assert "provider" not in top


def test_does_not_mutate_host_static_schema():
    static = _host_like_builder_output()
    wrapped = make_schema_override(lambda: static)
    wrapped()
    # The original object handed back by the host must be untouched (deep-copy).
    assert "model" not in static["parameters"]["properties"]["tasks"]["items"]["properties"]
    assert "provider" not in static["parameters"]["properties"]["tasks"]["items"]["properties"]


def test_idempotent_across_calls():
    wrapped = make_schema_override(_host_like_builder_output)
    a = wrapped()
    b = wrapped()
    for out in (a, b):
        task_props = out["parameters"]["properties"]["tasks"]["items"]["properties"]
        assert set(("model", "provider")).issubset(task_props)


def test_unexpected_shape_degrades_gracefully():
    wrapped = make_schema_override(lambda: {"parameters": {"properties": {}}})
    out = wrapped()  # must not raise
    assert out == {"parameters": {"properties": {}}}


def test_non_dict_passthrough():
    wrapped = make_schema_override(lambda: None)
    assert wrapped() is None
