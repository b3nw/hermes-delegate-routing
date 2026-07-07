# Changelog

## 0.1.0 — unreleased

Initial release.

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
- Verified against hermes-agent **0.18.0** (main @ `2e34e5f`).
