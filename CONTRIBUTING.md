# Contributing

Thanks for your interest in `hermes-delegate-routing`.

## Development setup

```bash
git clone https://github.com/b3nw/hermes-delegate-routing
cd hermes-delegate-routing
uv run --extra dev pytest      # unit tests — no hermes-agent host needed (uses fakes)
```

## Checks

CI runs three gates; all must pass before a PR merges:

```bash
uv run --extra dev pytest      # unit tests (host-free)
uv run --extra dev ruff check .  # lint
uv run --extra dev mypy        # type-check
```

## Host-backed tests

`tests/test_integration_smoke.py` and `tests/test_e2e_routing.py` exercise the
plugin against a real hermes-agent. They self-skip when no host is importable, so
they don't affect the default run. To run them, put a hermes-agent checkout/install
on `PYTHONPATH` (see [`docs/CI_E2E_TESTING.md`](docs/CI_E2E_TESTING.md)):

```bash
PYTHONPATH=/path/to/hermes-agent:. \
  /path/to/hermes-agent/.venv/bin/python -m pytest \
  tests/test_integration_smoke.py tests/test_e2e_routing.py
```

## Design context

The plugin couples to host internals by design (there is no public seam for
per-task delegate routing). Before changing the monkeypatch seams, read
[`docs/DESIGN.md`](docs/DESIGN.md) — especially §6 (the three seams) and §10
(coupling & the signature guard). New host versions can drift; the guard turns
drift into a safe no-op, and the host-backed tests are how we confirm a version
still works.

## Pull requests

- Keep changes focused; update `CHANGELOG.md` under an unreleased/next-version
  heading.
- If you verified against a new hermes-agent version, note it in the README
  support table.

## Releasing

Publishing is automated via PyPI Trusted Publishing (OIDC) — no API token is
stored. To cut a release:

1. Bump the version in `pyproject.toml` and `hermes_delegate_routing/__init__.py`,
   and add a dated `CHANGELOG.md` entry.
2. Commit, then tag: `git tag vX.Y.Z && git push origin main --tags`.
3. The `release` workflow builds, runs `twine check`, and publishes to PyPI.

One-time PyPI setup (per project, before the first tag push): on
<https://pypi.org/manage/account/publishing/> add a pending publisher —
owner `b3nw`, repository `hermes-delegate-routing`, workflow `release.yml`,
environment `pypi`.
