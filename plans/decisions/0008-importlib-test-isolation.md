# Decision 0008: importlib test isolation for multi-library workspace

Status: `superseded`
Superseded by: [Decision 0009](0009-per-library-test-runs.md)
Date: `2026-04-01`

## Context

ChuMicro is a mono-workspace where multiple libraries each have their own `tests/` directory. When a second library (`gpio`) was scaffolded alongside `timing`, pytest raised `ImportPathMismatchError` because both libraries had `tests/__init__.py`, and pytest's default import mode treated them as the same `tests` package:

```
ImportPathMismatchError: ('tests.conftest',
  '.../gpio/tests/conftest.py',
  '.../timing/tests/conftest.py')
```

The default pytest import mode (`prepend`) inserts the test directory into `sys.path` and imports test modules as top-level packages. When two directories share the same name (`tests`), the second one collides with the first.

## Decision

Use `--import-mode=importlib` in the root `pyproject.toml` pytest config. This mode uses Python's `importlib` machinery to import each test file independently, avoiding the shared-package collision.

Structural constraints that follow:

1. Library `tests/` directories **must not** contain `__init__.py`.
2. Test files use **absolute** mock imports (`from mocks.fake_ticks import FakeTicks`), not relative (`from .mocks.fake_ticks import ...`).
3. Each library's `tests/conftest.py` adds its own tests directory to `sys.path` so that absolute imports of local mocks resolve correctly.
4. The `mocks/` subdirectory inside `tests/` **does** keep its `__init__.py` (it is a regular package, not a test directory).
5. The root `conftest.py` adds all `src/` directories to `sys.path` so library packages are importable without pip install.

## Consequences

- New libraries created by `new-library` follow this pattern automatically (the scaffolder does not generate `tests/__init__.py`).
- Contributors must not add `__init__.py` to `tests/` directories; doing so will break test collection when more than one library exists.
- Relative imports inside test files are not supported under this mode.
- This is a permanent constraint for the lifetime of the mono-workspace layout.
