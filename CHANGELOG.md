# Changelog

## 0.1.1 — 2026-07-24

Initial public release.

- Per-task `model` / `provider` routing for `delegate_task` via `tasks[i].model`
  and `tasks[i].provider` (top-level args are dropped by the host and are not
  supported — matches upstream's recommended call shape).
- Three-seam, load-time monkeypatch of `tools.delegate_tool`
  (schema advertise → capture per-task creds → apply per child), because
  `delegate_task` bypasses the tool registry (so `register_tool(override=True)`
  can't intercept it). Signature-guarded and idempotent; degrades to a no-op on
  an unsupported host.
- Vendored model/provider resolver reusing the host `/model` switch pipeline;
  reads `parse_model_flags` positionally to tolerate return-arity drift.
- `on_error: fail | fallback` config toggle (default `fail`).
- Tier-1 end-to-end test (`tests/test_e2e_routing.py`) asserting per-task creds
  reach the child's OpenAI client boundary, wired as an opt-in CI `e2e` job.
- CI lint/type-check gates (`ruff`, `mypy`) alongside the host-free unit matrix.
- Verified against upstream hermes-agent **0.19.0** (tag `v2026.7.20`) and
  **0.18.0**. On 0.19.0 the two new `_build_child_agent` params
  (`override_max_tokens`, `override_request_overrides`) pass through the apply
  seam's keyword forwarding unchanged.

Packaging: dropped the unused `plugin.yaml` — the host reads it only for
directory plugins, never for pip/entry-point plugins like this one.
