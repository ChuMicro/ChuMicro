# Decision 0009: Per-library test runs

Status: `accepted`
Date: `2026-04-01`
Supersedes: [Decision 0008](0008-importlib-test-isolation.md)

## Context

Decision 0008 introduced `--import-mode=importlib` to work around pytest's `ImportPathMismatchError` when multiple libraries each had a `tests/` directory. This worked but imposed constraints: no `__init__.py` in test directories, absolute-only mock imports, and per-library conftest boilerplate for `sys.path` setup.

The underlying problem was that a single pytest invocation from the repo root collects all `tests/` directories and treats them as the same Python package. Rather than patching the import system, the simpler fix is to avoid the collision entirely by running pytest once per library.

## Decision

`scripts/run.py test` runs a separate pytest subprocess for each package that has a `tests/` directory. Coverage data from each run is written to a per-library file (`.coverage.<name>`), then combined with `coverage combine` and reported once at the end.

This eliminates the need for `--import-mode=importlib` and all of its structural constraints.

Key mechanics:

1. Each pytest run targets a single library's `tests/` directory.
2. `PYTHONPATH` is set to include all `src/` directories (via `_pythonpath_env()`), so cross-library imports work.
3. `COVERAGE_FILE` is set per-run so coverage data doesn't collide.
4. Each library must independently meet the 90% coverage threshold.  When `-k` filtering is active or `--no-cov` is set, per-library gates are skipped since filtering naturally reduces coverage.
5. Exit code 5 (no tests collected) is treated as success — it occurs when `-k` filters match nothing in a particular library.

## Consequences

- `--import-mode=importlib` is removed from `pyproject.toml`.
- Libraries can use `__init__.py` in `tests/` and relative imports if desired.
- No per-library conftest boilerplate is needed for `sys.path` setup (root conftest + PYTHONPATH handle it).
- Shared test fakes ship with their library (e.g., `chumicro_timing.testing.FakeTicks`) and are importable from any library's tests.
- Each library's test setup looks like a standard standalone Python project.
- Extracting a library from the mono-workspace requires no test infrastructure changes.
- Bare `pytest` from the repo root is no longer the supported path; use `python scripts/run.py test`.
