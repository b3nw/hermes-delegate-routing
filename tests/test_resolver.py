"""Tests for the vendored model/provider override resolver.

Ported from upstream PR #36790's resolver coverage. Runs against fake
``hermes_cli.*`` modules (see conftest) or a real host — tests patch the module
attributes either way.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from hermes_delegate_routing.resolver import resolve_model_provider_override


def _parent():
    return SimpleNamespace(provider="anthropic", model="opus", base_url="", api_key="")


def _switch_result(**kw):
    base = dict(
        success=True,
        new_model=None,
        target_provider=None,
        base_url=None,
        api_key=None,
        api_mode=None,
        error_message=None,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def test_resolves_model_with_structured_provider():
    with patch("hermes_cli.model_switch.switch_model") as mock_switch, patch(
        "hermes_cli.runtime_provider.resolve_runtime_provider",
        return_value={"command": None, "args": []},
    ):
        mock_switch.return_value = _switch_result(
            new_model="stepfun/step-3.5-flash", target_provider="openrouter"
        )
        creds = resolve_model_provider_override(
            model_input="stepfun/step-3.5-flash",
            provider_input="openrouter",
            parent_agent=_parent(),
        )
    assert creds["provider"] == "openrouter"
    assert creds["model"] == "stepfun/step-3.5-flash"
    assert mock_switch.call_args.kwargs["explicit_provider"] == "openrouter"


def test_resolves_inline_provider_flag():
    with patch("hermes_cli.model_switch.switch_model") as mock_switch, patch(
        "hermes_cli.runtime_provider.resolve_runtime_provider",
        return_value={"command": None, "args": []},
    ):
        mock_switch.return_value = _switch_result(
            new_model="stepfun/step-3.5-flash", target_provider="openrouter"
        )
        resolve_model_provider_override(
            model_input="stepfun/step-3.5-flash --provider openrouter",
            provider_input=None,
            parent_agent=_parent(),
        )
    assert mock_switch.call_args.kwargs["explicit_provider"] == "openrouter"


def test_conflicting_structured_and_inline_provider_fails():
    with pytest.raises(ValueError) as ctx:
        resolve_model_provider_override(
            model_input="sonnet --provider anthropic",
            provider_input="openrouter",
            parent_agent=_parent(),
        )
    assert "Conflicting provider overrides" in str(ctx.value)


def test_empty_input_fails():
    with pytest.raises(ValueError) as ctx:
        resolve_model_provider_override(
            model_input="", provider_input=None, parent_agent=_parent()
        )
    assert "empty" in str(ctx.value)


def test_switch_model_failure_raises():
    with patch("hermes_cli.model_switch.switch_model") as mock_switch:
        mock_switch.return_value = _switch_result(
            success=False, error_message="no such model"
        )
        with pytest.raises(ValueError) as ctx:
            resolve_model_provider_override(
                model_input="nope", provider_input=None, parent_agent=_parent()
            )
    assert "no such model" in str(ctx.value)


def test_tolerates_parse_model_flags_arity_growth():
    """Regression: host parse_model_flags gained a 5th return value (is_session);
    the resolver must read only elements [0]/[1] and ignore the growing tail."""
    with patch(
        "hermes_cli.model_switch.parse_model_flags",
        return_value=("m", "", 0, 0, 0, "future"),
    ), patch("hermes_cli.model_switch.switch_model") as mock_switch, patch(
        "hermes_cli.runtime_provider.resolve_runtime_provider",
        return_value={"command": None, "args": []},
    ):
        mock_switch.return_value = _switch_result(new_model="m", target_provider="anthropic")
        creds = resolve_model_provider_override(
            model_input="m", provider_input=None, parent_agent=_parent()
        )
    assert creds["model"] == "m"


def test_model_only_same_provider_takes_effect():
    with patch("hermes_cli.model_switch.switch_model") as mock_switch, patch(
        "hermes_cli.runtime_provider.resolve_runtime_provider",
        return_value={"command": None, "args": []},
    ):
        mock_switch.return_value = _switch_result(
            new_model="glm-5", target_provider="anthropic"
        )
        creds = resolve_model_provider_override(
            model_input="glm-5", provider_input=None, parent_agent=_parent()
        )
    assert creds["model"] == "glm-5"
    assert creds["provider"] == "anthropic"
