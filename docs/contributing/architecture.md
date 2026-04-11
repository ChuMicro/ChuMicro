# How the Codebase Works

A quick orientation for advanced contributors. Read this if you want to understand the machinery behind `scripts/run.py`, the test infrastructure, or the release pipeline — not just the libraries themselves.

## Reading order

If you want to read the source code, this is the fastest path:

1. `libraries/timing/src/chumicro_timing/ticks.py` (120 lines) — tick contract, runtime detection
2. `libraries/timing/src/chumicro_timing/heartbeat.py` (80 lines) — periodic timer
3. `libraries/runner/src/chumicro_runner/core.py` (350 lines) — task scheduler, the most complex file
4. `libraries/msgpack/src/chumicro_msgpack/_pure.py` (370 lines) — msgpack encoder/decoder
5. `libraries/compat/src/chumicro_compat/functools.py` (65 lines) — polyfill pattern

After reading these five files, you understand ~80% of the project.

## Package discovery

`scripts/run.py` is the single entry point for all developer tasks. It delegates to task-specific modules in `scripts/`.

Package discovery (`scripts/workspace.py`) scans the workspace for `pyproject.toml` files under `libraries/` and `support/`. There are no hard-coded package lists — adding a library via `new-library` automatically makes it visible to all tasks (test, lint, build, docs, verify-examples).

## Test isolation

Each library is tested in its own pytest subprocess (`scripts/run.py test` spawns one process per package). This prevents import collisions between libraries that might have identically-named test files. See [Decision 0009](../../plans/decisions/0009-per-library-test-runs.md).

The root `conftest.py` auto-discovers `src/` directories and adds them to `sys.path` so pytest can resolve imports without editable installs. Coverage is measured per-library with a 94% branch threshold.

## Cross-runtime test harness

Tests under `tests/` in each library are written to be cross-runtime compatible. They use `chumicro_test_harness.raises` instead of `pytest.raises`, and plain `assert` instead of pytest-specific matchers.

The harness (`support/test_harness/`) discovers and runs these same test files on MicroPython and CircuitPython unix ports. Files that fail to import (e.g., because they use `monkeypatch` or other pytest-only features) are skipped automatically — the harness reports them as skipped, not failed.

Cross-runtime tests run during `preflight` and in CI via `test-micropython-compatibility` and `test-circuitpython-compatibility` tasks.

## Docs and versioning

Each library has its own `mkdocs.yml` and `docs/` directory. Documentation is built per-library with [MkDocs](https://www.mkdocs.org/) + [Material](https://squidfunk.github.io/mkdocs-material/) + [mkdocstrings](https://mkdocstrings.github.io/).

Versioning uses [mike](https://github.com/jimporter/mike): each library gets `stable` and `experimental` doc versions deployed to GitHub Pages. The `docs-deploy` workflow handles this in CI. Locally, `python scripts/run.py docs-preview` deploys to a local gh-pages branch and serves a versioned preview.

## Release pipeline

Releases are automated via GitHub Actions:

1. **Experimental** — `release.yml` fires when a PR with a VERSION bump merges to `main`. It builds the package, publishes to PyPI (as `chumicro-<name>-experimental`), pushes to the experimental bundle repo, creates a git tag, and deploys experimental docs.

2. **Stable** — `promote.yml` is triggered manually by a maintainer. It re-builds from the same source, publishes to PyPI (as `chumicro-<name>`), pushes to the stable bundle repo, creates a stable git tag, and deploys stable docs.

Both use OIDC trusted publishing — no stored PyPI tokens. See [Decision 0019](../../plans/decisions/0019-branching-model.md) and [Decision 0018](../../plans/decisions/0018-distribution-bundle-repo.md).

## CI pipeline

`ci.yml` runs on PRs and pushes to `main`:

| Job | What it checks |
|-----|---------------|
| `lint` | Ruff across the workspace |
| `test` | pytest on CPython 3.11, 3.12, 3.13 with 94% coverage |
| `verify-examples` | All example scripts parse and resolve imports |
| `docs` | MkDocs builds cleanly, no griffe warnings |
| `build` | Package distributions build successfully |
| `check-version` | VERSION bumped when `src/` files changed |
| `check-api` | No removed/renamed public symbols without VERSION bump |
| `micropython-compat` | Cross-runtime tests under MicroPython unix port |
| `circuitpython-compat` | Cross-runtime tests under CircuitPython unix port |

Running `python scripts/run.py preflight` locally mirrors this entire pipeline.

## IDE configs

`scripts/ide_sync.py` generates configuration files for multiple editors:

- **PyCharm** — `.idea/chumicro.iml` (source roots) and `.idea/runConfigurations/*.xml` (run configs)
- **VS Code** — `.vscode/settings.json` (extraPaths) and `.vscode/tasks.json` (task runner)
- **Pyright** — `pyrightconfig.json` (extraPaths for any Pyright-based LSP)

`python scripts/run.py sync-ide` regenerates all of these from the current workspace structure. It's called automatically during `setup` and `new-library`.

