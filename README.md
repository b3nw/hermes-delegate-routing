# hermes-delegate-routing

**A fork-free [Hermes Agent](https://github.com/NousResearch/hermes-agent) plugin that adds explicit per-task `model` / `provider` routing to `delegate_task`.**

Route each subagent in a batch delegation to a different model/provider:

```jsonc
delegate_task(tasks=[
  {"goal": "Summarize these logs",      "model": "gemini-flash-2.0", "provider": "openrouter"},
  {"goal": "Review this diff for bugs", "model": "sonnet",           "provider": "anthropic"},
  {"goal": "Research the CVE",          "model": "deepseek-pro",     "provider": "deepseek"}
])
```

Per-task delegate routing was proposed upstream and not accepted; this plugin
delivers it as a standalone package, so there is no fork to maintain. Full design
and rationale: [`docs/DESIGN.md`](docs/DESIGN.md).

## Install

Install into the **same environment** as your hermes-agent, then enable it.

```bash
pip install hermes-delegate-routing
# or, for development from a checkout:
pip install -e /path/to/hermes-delegate-routing
```

The pip entry point (`hermes_agent.plugins`) makes hermes-agent auto-discover the
plugin; you still have to enable it in `config.yaml`:

```yaml
plugins:
  enabled: [delegate_routing]

# optional:
delegate_routing:
  on_error: fail   # "fail" (default) → a bad model/provider fails the call;
                   # "fallback"       → skip the override, use batch creds, log a warning
```

No `allow_tool_override` grant is needed — the plugin does not use the registry
override API (see "How it works").

## Usage

Put routing fields inside `tasks[]` — **even for a single task**:

```python
delegate_task(tasks=[{"goal": "…", "model": "sonnet", "provider": "anthropic"}])
```

- `model` — a model name/alias as used by `/model` (e.g. `sonnet`,
  `gemini-flash-2.0`), optionally with inline `--provider <id>`.
- `provider` — a configured provider id. Prefer this structured field over
  embedding `--provider` in `model`.
- Precedence: per-task `tasks[i]` → `delegation.*` config → parent agent.
- A task with no `model`/`provider` inherits the normal delegation model.

**Top-level `delegate_task(model=…, provider=…)` is intentionally not supported** —
the host drops top-level args before the tool runs, so only `tasks[]` fields take
effect. This matches the recommended call shape (see [`docs/DESIGN.md`](docs/DESIGN.md)).

## How it works

`delegate_task` is special-cased in the host runtime
(`agent/agent_runtime_helpers.py`) to bypass the tool registry, so the sanctioned
`register_tool(override=True)` mechanism can't intercept it. Instead the plugin
installs three narrow, idempotent monkeypatches on `tools.delegate_tool` at load:

1. **schema** — advertise `tasks[].model` / `tasks[].provider` to the model
   (via the registered `ToolEntry`);
2. **capture** — wrap `delegate_task` to resolve per-task creds (reusing the
   host `/model` switch pipeline) and stash them by task index;
3. **apply** — wrap `_build_child_agent` to inject those creds per child.

If the host isn't importable or its function signatures don't match,
`apply_patches()` **refuses to patch** and the plugin degrades to a no-op — core
behavior is never left half-patched. See [`docs/DESIGN.md`](docs/DESIGN.md).

## Supported versions

Verified against upstream [`NousResearch/hermes-agent`](https://github.com/NousResearch/hermes-agent):

| hermes-agent | Status |
|---|---|
| `0.19.0` (tag [`v2026.7.20`](https://github.com/NousResearch/hermes-agent/releases/tag/v2026.7.20)) | ✅ verified — seams, resolver, Tier-1 end-to-end routing, and the real host plugin-loader path all exercised against the host |
| `0.18.0` | ✅ verified (earlier release) |

Because the plugin depends on host internals, new hermes-agent releases can
drift. The signature guard turns drift into a **safe no-op with a loud log**, not
a crash. File an issue if you hit an INACTIVE warning on a newer version.

## Development

```bash
uv run --extra dev pytest            # unit tests (no host needed; uses fakes)
uv run --extra dev ruff check .      # lint
uv run --extra dev mypy              # type-check

# host-backed tests (integration smoke + Tier-1 e2e) against a real host —
# they self-skip when no host is importable:
PYTHONPATH=/path/to/hermes-agent:. \
  /path/to/hermes-agent/.venv/bin/python -m pytest tests/test_integration_smoke.py tests/test_e2e_routing.py
```

The host-backed tests also run in CI as an opt-in `e2e` job — see
[`docs/CI_E2E_TESTING.md`](docs/CI_E2E_TESTING.md).

## License

MIT
