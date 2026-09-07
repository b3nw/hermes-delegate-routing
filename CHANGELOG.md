# Changelog

## 0.1.3 — 2026-09-07

### Fixed

- **Never import `model_tools` from cache invalidation (import-lock deadlock).**
  In Hermes Agent v0.19+, `model_tools` runs plugin discovery at module import.
  When plugin discovery ran on a background thread while the main thread was
  mid-import of `model_tools`, importing `model_tools` from
  `_invalidate_tool_defs_cache` blocked on the interpreter's per-module import
  lock forever — causing every agent CLI turn to hang indefinitely (#1 by
  @diogo7dias). Cache invalidation now inspects `sys.modules.get("model_tools")`
  without triggering an import; if not loaded, the `_generation` bump already
  guarantees a cold cache on first build.
- Added regression test `test_invalidation_never_imports_model_tools` with a
  meta_path tripwire proving `_patch_schema` never triggers `model_tools` import.
- Fixed test goal length validation and idempotency assertions.

## 0.1.2 — 2026-07-24

### Fixed

- **Seam A now invalidates the host's tool-definitions cache.** Advertising
  `tasks[].model`/`.provider` mutates `entry.dynamic_schema_overrides` directly,
  which does not bump `registry._generation`. `model_tools.get_tool_definitions`
  (the agent loop's `quiet_mode=True` fast path) memoizes on that generation, so
  a long-running gateway that cached the stock `delegate_task` schema *before*
  the plugin patched kept serving the field-less schema for the life of the
  process — the LLM never saw the new fields and per-task routing silently
  no-op'd. `_patch_schema` now bumps `registry._generation` and clears
  `_tool_defs_cache` after wrapping the entry (both best-effort/guarded).
  Regression test in `tests/test_schema_cache_invalidation.py`.

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
