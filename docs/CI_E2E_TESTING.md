# End-to-End / CI Testing Design

Design notes for automating end-to-end routing tests — proving a real subagent
actually *connects* to the routed model/provider. Grounded against hermes-agent
0.18.0.

**Status:** Tier 1 is implemented and shipped as `tests/test_e2e_routing.py`. It
self-skips without a host and runs in CI via the opt-in `e2e` job (see
[CI wiring](#ci-wiring)). Tiers 2–3 remain future work.

## The gap

The shipped tests verify the seams install, the schema advertises
`tasks[].model/provider`, creds resolve, and per-task creds land on
`_build_child_agent` by index. What they don't verify: that `override_base_url` /
`model` actually reach the child's outbound HTTP request.

## Core idea

- The routing assertion needs an endpoint that **records which model/base_url each
  subagent requested** — not a real model. A recording mock (or patched SDK) is
  deterministic, fast, and secret-free. A real multi-model LLM proxy is
  **sufficient but not necessary** for the routing gate; its value is a **nightly
  canary** against real providers' auth/wire quirks.
- The test only has value **through the plugin**: vanilla `delegate_task` uses one
  cred bundle for the whole batch, so per-task routing is exactly what the seams
  add.
- **The gating cost is CI infra, not the test.** hermes-agent isn't a plain PyPI
  package — CI must install it from git at a pinned SHA (heavy deps, cache them).
  Each test tier is ~1 file.

## Enabling facts (verified, hermes-agent 0.18.0)

- **Template to copy:** `tests/run_agent/test_real_interrupt_subagent.py` builds a
  real parent + child `AIAgent`, calls `_run_single_child(...)`, and intercepts the
  OpenAI SDK via `patch('run_agent.OpenAI')` with a fake `chat.completions.create`
  (and patches `_build_system_prompt`).
- **base_url/model reach the wire:** `_build_child_agent` passes
  `effective_base_url/api_key/provider/model` into `AIAgent(...)`; the client is
  built via `create_openai_client → OpenAI(api_key=, base_url=)`
  (`agent/auxiliary_client.py`), and `model=` rides in
  `chat.completions.create(**api_kwargs)` (`agent/chat_completion_helpers.py`).
  Provider auth headers attach to `_client_kwargs["default_headers"]`.
- **Single-shot child:** the loop is bounded by `api_call_count < max_iterations`;
  `max_iterations=1` + a response with no tool calls = one `.create()` then exit.
- **Synchronous run:** `background=False` (default) runs inline and returns JSON;
  avoid `background=True` (returns a handle).
- **Custom endpoint config:** `provider: "custom"` + `base_url:` (no catalog
  needed; a made-up model id passes straight through), or `providers:` /
  `custom_providers:` entries. For the `/model` resolver path, a `model_aliases:`
  entry is checked before the models.dev catalog.
- **Built-in observability:** the delegate result JSON reports the requested
  `model` per subagent; assert the *actual* endpoint at the SDK boundary
  (`OpenAI.call_args["base_url"]`, `create(model=...)`).

## Tiers

| Tier | Proves | Proxy? | Effort |
|---|---|---|---|
| 1. SDK-boundary E2E | capture→apply→child→client (minus socket) | No | Low–moderate |
| 2. Real-socket E2E | real httpx egress + provider headers | Optional (local recorder *or* a proxy) | Moderate (+~60-line recorder) |
| 3. LLM-driven | schema advertisement + a real model choosing per-task | Yes | High, flaky → nightly only |

**Tier 1 (recommended gate — implemented in `tests/test_e2e_routing.py`):** build a
real parent `AIAgent`, activate the plugin, patch `run_agent.OpenAI` with a
recording fake, mock the `switch_model` catalog boundary to two distinct bundles,
call `delegate_task(tasks=[{…m1…},{…m2…}], background=False)`, and assert both
routed `base_url`/`model` pairs reach the client boundary. Deterministic, no
network.

**Tier 2:** as Tier 1 but point `custom_providers.base_url` at a local
`BaseHTTPRequestHandler` (or a proxy) that records `(path, model)` and returns a
minimal chat-completion; assert the recorder's log maps each nonce → model.

**Tier 3:** a real model reads the augmented schema and picks per-task models;
flaky, nightly only.

## CI wiring

The Tier-1 gate is wired as the opt-in **`e2e` job** in
`.github/workflows/ci.yml`. It is **gated on two repository variables** so a fresh
clone stays green until a host source is configured:

- `HERMES_AGENT_REPO` — e.g. `NousResearch/hermes-agent` (the `owner/repo` to
  install from).
- `HERMES_AGENT_REF` — a pinned SHA/tag to test against (e.g. `v2026.7.20` for
  hermes-agent 0.19.0).

When both are set, the job installs the host
(`uv pip install "hermes-agent @ git+https://github.com/$REPO@$REF"`) plus the
plugin, then runs `tests/test_integration_smoke.py` and `tests/test_e2e_routing.py`.
The workflow also has a weekly `schedule`; point `HERMES_AGENT_REF` at `main` for a
**host-drift canary** (the signature guard already no-ops loudly, so drift surfaces
as a failed assertion rather than a crash).

Remaining, still-optional work:

1. **Tier-2 job:** add the local recorder + a two-`custom`-provider config fixture
   for real-socket egress + provider-header assertions.
2. **Nightly cron:** Tier-2/3 against a real proxy; base_url + key from secrets;
   allowed to be alerting rather than blocking.
3. **Version matrix:** install a couple of host versions and cache each venv (the
   host install is the main cost).

## Reference files (host)

`tests/run_agent/test_real_interrupt_subagent.py`, `tests/tools/test_delegate.py`,
`tools/delegate_tool.py` (`_build_child_agent`, `_run_single_child`, per-subagent
result `model`), `agent/chat_completion_helpers.py`, `agent/auxiliary_client.py`,
`agent/conversation_loop.py`, `hermes_cli/config.py`, `cli-config.yaml.example`.
