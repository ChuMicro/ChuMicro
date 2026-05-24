# Decision 0008: importlib test isolation for multi-library workspace

Status: `superseded`
Date: `2026-04-01`
Summary: Used pytest's `--import-mode=importlib` to dodge `ImportPathMismatchError` between sibling-library `tests/` directories; introduced no-`__init__.py` constraints.
Related: Decision 0001 (mono-workspace layout)
Superseded by: [Decision 0009](0009-per-library-test-runs.md)

## Context

ChuMicro is a mono-workspace where multiple libraries each have their own `tests/` directory. When a second library (`gpio`) was scaffolded alongside `timing`, pytest raised `ImportPathMismatchError` because both libraries had `tests/__init__.py`, and pytest's default import mode treated them as the same `tests` package:

```
ImportPathMismatchError: ('tests.conftest',
  '.../gpio/tests/conftest.py',
  '.../timing/tests/conftest.py')
```

The default pytest import mode (`prepend`) inserts the test directory into `sys.path` and imports test modules as top-level packages. When two directories share the same name (`tests`), the second one collides with the first.

## Decision

Used `--import-mode=importlib` in the root `pyproject.toml` pytest config.  This mode uses Python's `importlib` machinery to import each test file independently, avoiding the shared-package collision.  Structural constraints that followed: no `__init__.py` in library `tests/` directories; absolute mock imports only (`from mocks.fake_ticks import FakeTicks`); each library's `tests/conftest.py` added its own tests directory to `sys.path`; the `mocks/` subdirectory kept its `__init__.py`; the root `conftest.py` added all `src/` directories to `sys.path`.

Superseded by [Decision 0009](0009-per-library-test-runs.md), which moved to per-library `pytest` invocations and removed the global `--import-mode=importlib` flag from library configs.

## Consequences

- During the importlib-mode era: contributors could not add `__init__.py` to `tests/` directories, and relative imports inside test files were unsupported.
- Per-library pytest invocations under Decision 0009 removed both constraints.
