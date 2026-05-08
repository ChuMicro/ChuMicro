# Decision 0009: Per-library test runs

Status: `accepted`
Date: `2026-04-01`
Related: Decision 0001 (mono-workspace layout), Decision 0025 (coverage thresholds)
Supersedes: [Decision 0008](0008-importlib-test-isolation.md)

## Context

Decision 0008 introduced `--import-mode=importlib` to work around pytest's `ImportPathMismatchError` when multiple libraries each had a `tests/` directory. This worked but imposed constraints: no `__init__.py` in test directories, absolute-only mock imports, and per-library conftest boilerplate for `sys.path` setup.

The underlying problem was that a single pytest invocation from the repo root collects all `tests/` directories and treats them as the same Python package. Rather than patching the import system, the simpler fix is to avoid the collision entirely by running pytest once per library.

## Decision

`scripts/run.py test` runs a separate pytest subprocess for each package that has a `tests/` directory. Coverage data from each run is written to a per-library file (`.coverage.<name>`), then combined with `coverage combine` and reported once at the end.

This is the commit-gating path. The repo also keeps a root-level pytest config (`pyproject.toml` + `conftest.py`) so that bare `pytest` from the repo root works for IDE Testing-panel discovery and ad-hoc development; that path doesn't enforce per-library coverage thresholds. `--import-mode=importlib` stays in the root `addopts` because two workbench packages (`workbench/deploy/tests/` and `workbench/repl/tests/`) ship test files with the same unqualified module name (`test_cli.py`, `test_recovery.py`) and classic prepend-mode collides on those.

Key mechanics:

1. Each pytest run targets a single library's `tests/` directory.
2. `PYTHONPATH` is set to include all `src/` directories (via `_pythonpath_env()`), so cross-library imports work.
3. `COVERAGE_FILE` is set per-run so coverage data doesn't collide.
4. Each library must independently meet the coverage threshold (configured in `pyproject.toml`).  When `-k` filtering is active or `--no-cov` is set, per-library gates are skipped since filtering naturally reduces coverage.
5. Exit code 5 (no tests collected) is treated as success — it occurs when `-k` filters match nothing in a particular library.

## Consequences

- `python scripts/run.py test` is the commit-gating path: it enforces each library's coverage threshold (configured in its `pyproject.toml`), parallelizes per-package, and is what CI runs.
- Bare `pytest` from the repo root is also supported, for IDE Testing-panel discovery and ad-hoc development. The root `pyproject.toml` + `conftest.py` discover source roots, set `--import-mode=importlib` (so workbench packages can share unqualified test-module names like `test_cli.py` across `workbench/deploy/tests/` and `workbench/repl/tests/` without colliding), route `functional_tests/` to the `chumicro-pytest-device` plugin, and deselect hardware tests on default sweeps. This path does not gate coverage.
- Libraries can use `__init__.py` in `tests/` and relative imports if desired.
- Shared test fakes ship with their library (e.g., `chumicro_timing.testing.FakeTicks`) and are importable from any library's tests.
- Each library's test setup looks like a standard standalone Python project.
- Extracting a library from the mono-workspace requires no test infrastructure changes.
