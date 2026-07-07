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


def _install_fake_hermes_cli() -> None:
    try:  # real host present → use it, tests patch the real attributes
        import hermes_cli.model_switch  # noqa: F401
        import hermes_cli.config  # noqa: F401
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
