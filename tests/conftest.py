"""Test bootstrap.

Unit tests are meant to run WITHOUT a real hermes-agent install. This module
injects minimal fake ``hermes_cli.*`` modules into ``sys.modules`` when the real
host is not importable, so the lazily-imported host functions in
``resolver.py`` resolve to stubs that individual tests then patch
(``unittest.mock.patch("hermes_cli.model_switch.switch_model")`` etc.).

If a real hermes-agent IS importable, we leave it alone and let tests patch the
real attributes — the same test code works either way.
"""

from __future__ import annotations

import sys
import types

import pytest


def _install_fake_hermes_cli() -> None:
    try:  # real host present → use it, tests patch the real attributes
        import hermes_cli.config  # noqa: F401
        import hermes_cli.model_switch  # noqa: F401
        import hermes_cli.runtime_provider  # noqa: F401
        return
    except Exception:
        pass

    def _fake_parse_model_flags(raw):
        raw = raw or ""
        provider = ""
        model = raw
        if "--provider" in raw:
            head, _, tail = raw.partition("--provider")
            tail = tail.strip()
            provider = tail.split()[0] if tail else ""
            model = head.strip()
        # Mirror the current host: 5-tuple (model, provider, is_global,
        # force_refresh, is_session). Resolver reads only [0] and [1].
        return (model.strip(), provider, False, False, False)

    def _fake_switch_model(**kwargs):  # must be patched by tests that reach it
        raise AssertionError("switch_model must be patched in tests")

    def _fake_load_config():
        return {}

    def _fake_resolve_runtime_provider(requested=None, target_model=None):
        return {"command": None, "args": []}

    pkg = types.ModuleType("hermes_cli")
    pkg.__path__ = []  # mark as package
    ms = types.ModuleType("hermes_cli.model_switch")
    ms.parse_model_flags = _fake_parse_model_flags
    ms.switch_model = _fake_switch_model
    cfg = types.ModuleType("hermes_cli.config")
    cfg.load_config = _fake_load_config
    rp = types.ModuleType("hermes_cli.runtime_provider")
    rp.resolve_runtime_provider = _fake_resolve_runtime_provider

    # Attach submodules as attributes on the parent package too — not just in
    # sys.modules. unittest.mock.patch("hermes_cli.model_switch.<attr>") resolves
    # the target via getattr(hermes_cli, "model_switch"), which (on Python 3.10)
    # is NOT satisfied by a sys.modules entry alone.
    pkg.model_switch = ms
    pkg.config = cfg
    pkg.runtime_provider = rp

    sys.modules["hermes_cli"] = pkg
    sys.modules["hermes_cli.model_switch"] = ms
    sys.modules["hermes_cli.config"] = cfg
    sys.modules["hermes_cli.runtime_provider"] = rp


_install_fake_hermes_cli()


@pytest.fixture(autouse=True)
def _restore_host_delegate_state():
    """Isolate tests that monkeypatch the real host.

    ``apply_patches()`` mutates ``tools.delegate_tool`` module globals (and the
    registered ToolEntry) in place and marks them with a sentinel. Several
    host-requiring tests install those patches; without teardown the first one
    to run leaves the module patched, so a later test that asserts a *fresh*
    install sees an already-wrapped function (and order becomes significant).

    This fixture snapshots the mutated attributes before each test and restores
    them after, so every host test starts from a pristine host regardless of
    order. It is a no-op in the default unit environment, where the real host
    is not importable.
    """
    try:
        import tools.delegate_tool as dt
    except Exception:
        yield
        return

    saved_delegate = dt.delegate_task
    saved_build_child = dt._build_child_agent
    had_flag = hasattr(dt, "_HDR_PATCHED")
    saved_flag = getattr(dt, "_HDR_PATCHED", None)

    entry = None
    saved_schema = None
    try:
        from tools.registry import registry

        entry = registry.get_entry("delegate_task")
        if entry is not None:
            saved_schema = getattr(entry, "dynamic_schema_overrides", None)
    except Exception:
        entry = None

    try:
        yield
    finally:
        dt.delegate_task = saved_delegate
        dt._build_child_agent = saved_build_child
        if had_flag:
            dt._HDR_PATCHED = saved_flag
        elif hasattr(dt, "_HDR_PATCHED"):
            del dt._HDR_PATCHED
        if entry is not None:
            entry.dynamic_schema_overrides = saved_schema
