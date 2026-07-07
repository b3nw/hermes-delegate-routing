"""Integration smoke test — runs only when a real hermes-agent host is importable.

Skipped cleanly in the default unit environment (no host on the path). To run it,
put a hermes-agent checkout / install on PYTHONPATH, e.g.:

    PYTHONPATH=/path/to/hermes-agent:. \\
      /path/to/hermes-agent/.venv/bin/python -m pytest tests/test_integration_smoke.py

NOTE: this mutates the real host module in-process (installs the monkeypatches).
That's fine for a dedicated run; it's why the test self-skips by default.
"""

from __future__ import annotations

import pytest

dt = pytest.importorskip("tools.delegate_tool", reason="no hermes-agent host on path")
registry_mod = pytest.importorskip("tools.registry", reason="no hermes-agent host on path")


def test_apply_patches_against_real_host():
    from hermes_delegate_routing.patches import apply_patches

    orig_delegate = dt.delegate_task
    orig_build = dt._build_child_agent

    assert apply_patches() is True, "plugin should activate on a supported host"
    assert dt.delegate_task is not orig_delegate, "capture seam (B) not installed"
    assert dt._build_child_agent is not orig_build, "apply seam (C) not installed"

    # Seam A: the real ToolEntry now advertises the per-task fields.
    entry = registry_mod.registry.get_entry("delegate_task")
    schema = entry.dynamic_schema_overrides()
    props = schema["parameters"]["properties"]["tasks"]["items"]["properties"]
    assert "model" in props and "provider" in props

    # Idempotent.
    wrapped = dt.delegate_task
    assert apply_patches() is True
    assert dt.delegate_task is wrapped, "second apply must not re-wrap"


def test_resolver_against_real_parse_model_flags():
    """Resolver reads model/provider through the real parse_model_flags (arity may
    differ across host versions); switch_model is mocked so there's no network."""
    from types import SimpleNamespace
    from unittest.mock import patch

    from hermes_delegate_routing.resolver import resolve_model_provider_override

    with patch(
        "hermes_cli.model_switch.switch_model",
        return_value=SimpleNamespace(
            success=True, new_model="glm-5", target_provider="openrouter",
            base_url="https://example", api_key="k", api_mode=None, error_message=None,
        ),
    ):
        creds = resolve_model_provider_override(
            model_input="glm-5 --provider openrouter",
            provider_input=None,
            parent_agent=SimpleNamespace(provider="anthropic", model="opus", base_url="", api_key=""),
        )
    assert creds["model"] == "glm-5"
    assert creds["provider"] == "openrouter"
