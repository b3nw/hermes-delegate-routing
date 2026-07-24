"""Model/provider override resolver.

Vendored from the (rejected) upstream PR
https://github.com/NousResearch/hermes-agent/pull/36790 — the function
``_resolve_model_provider_override``. It reuses the host's ``/model`` switch
pipeline so aliases, provider catalogs, custom providers, and ``--provider``
syntax resolve exactly as they do for the ``/model`` command.

We vendor rather than import because this function only ever existed inside the
rejected PR; it is not in released hermes-agent. Host imports are done lazily
inside the function so (a) import failures degrade to a clear ValueError and
(b) unit tests can stub ``hermes_cli.*`` (see tests/conftest.py).

Returns a creds dict shaped like the host's
``_resolve_delegation_credentials`` so it flows straight into
``_build_child_agent``:
    {model, provider, base_url, api_key, api_mode, command, args}
"""

from __future__ import annotations

from typing import Any


def resolve_model_provider_override(
    *,
    model_input: str | None,
    provider_input: str | None,
    parent_agent,
) -> dict:
    """Resolve an explicit delegate_task model/provider override.

    Raises ValueError on empty/unparseable/conflicting input or a failed switch.
    """
    raw_model = str(model_input or "").strip()
    explicit_provider = str(provider_input or "").strip()
    if not raw_model and not explicit_provider:
        raise ValueError("model/provider override is empty")

    try:
        from hermes_cli.model_switch import parse_model_flags, switch_model
    except Exception as exc:  # pragma: no cover - defensive import guard
        raise ValueError(
            f"Cannot import model switch resolver for delegation override: {exc}"
        ) from exc

    # parse_model_flags returns (model, provider, *flags). The flag tail has
    # grown across host versions (4-tuple in PR #36790, 5-tuple today), so read
    # only the first two positionally to stay arity-agnostic.
    parsed = parse_model_flags(raw_model)
    parsed_model = parsed[0] if len(parsed) > 0 else ""
    parsed_provider = parsed[1] if len(parsed) > 1 else ""
    if explicit_provider and parsed_provider and explicit_provider != parsed_provider:
        raise ValueError(
            f"Conflicting provider overrides: provider={explicit_provider!r} "
            f"but model contains --provider {parsed_provider!r}."
        )
    provider_for_switch = explicit_provider or parsed_provider
    if not parsed_model and not provider_for_switch:
        raise ValueError(f"Could not parse model/provider override: {raw_model!r}")

    user_providers = None
    custom_providers = None
    try:
        from hermes_cli.config import load_config

        full_cfg = load_config()
        user_providers = full_cfg.get("providers")
        custom_providers = full_cfg.get("custom_providers")
    except Exception:  # pragma: no cover - config is best-effort
        pass

    result = switch_model(
        raw_input=parsed_model,
        current_provider=getattr(parent_agent, "provider", "") or "",
        current_model=getattr(parent_agent, "model", "") or "",
        current_base_url=getattr(parent_agent, "base_url", "") or "",
        current_api_key=getattr(parent_agent, "api_key", "") or "",
        is_global=False,
        explicit_provider=provider_for_switch,
        user_providers=user_providers,
        custom_providers=custom_providers,
    )
    if not result.success:
        raise ValueError(
            f"Cannot resolve delegation model/provider override "
            f"{raw_model or provider_for_switch!r}: "
            f"{result.error_message or 'unknown error'}"
        )

    creds: dict[str, Any] = {
        "model": result.new_model or None,
        "provider": result.target_provider or None,
        "base_url": result.base_url or None,
        "api_key": result.api_key or None,
        "api_mode": result.api_mode or None,
        "command": None,
        "args": [],
    }

    # Preserve runtime-provider metadata switch_model does not expose directly,
    # e.g. ACP command/args for subprocess-backed providers.
    if creds["provider"]:
        try:
            from hermes_cli.runtime_provider import resolve_runtime_provider

            runtime = resolve_runtime_provider(
                requested=creds["provider"],
                target_model=creds["model"],
            )
            creds["command"] = runtime.get("command")
            creds["args"] = list(runtime.get("args") or [])
        except Exception:  # pragma: no cover - runtime metadata is best-effort
            pass

    return creds
