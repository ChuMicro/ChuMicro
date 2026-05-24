# Decision 0011: Per-library platform targeting

Status: `accepted`
Date: `2026-04-02`
Summary: Each library declares supported runtimes in `pyproject.toml`'s `[tool.chumicro] platforms` list; absent key defaults to all three runtimes.
Related: Decision 0007 (cross-platform deps), Decision 0015 (board support tiers), Decision 0037 (per-runtime file marking)

## Context

ChuMicro targets three runtimes: CPython, MicroPython, and CircuitPython.  Most libraries should support all three, but some may only work on a subset — for example, a library wrapping a CircuitPython-only hardware API has no reason to be published to PyPI, and a CPython-only dev tool shouldn't be shipped as a `.mpy` bundle.

Release automation must know which platforms a library targets so it can skip irrelevant packaging and distribution channels.  The MP/CP unix-port test lane (`pytest ... --target unix-port --runtime <X>`) also needs to skip libraries that don't target the runtime under test.

## Decision

Each library declares its supported platforms in `pyproject.toml` under a `[tool.chumicro]` table:

```toml
[tool.chumicro]
platforms = ["cpython", "micropython", "circuitpython"]
```

The canonical platform identifiers are:
- `cpython`
- `micropython`
- `circuitpython`

### Defaults and rules

- If `[tool.chumicro]` or `platforms` is absent, the library targets **all three** runtimes.  This is the expected common case and avoids boilerplate.
- At least one platform must be listed when the key is present.
- The `platforms` list is the source of truth for:
  - which package managers receive release artifacts (PyPI for `cpython`, circup/bundle for `circuitpython`, etc.)
  - which runtimes exercise the library in the MP/CP unix-port pytest lane
  - any future per-platform CI gates

### Where it lives

`pyproject.toml` was chosen over a separate file because:
- it already exists for every package
- `[tool.*]` tables are the standard place for tool-specific metadata
- `scripts/run.py` already reads package directories by scanning for `pyproject.toml`, so adding a TOML read is a small incremental cost

### Reading the value

`chumicro-pytest-device` reads `[tool.chumicro].platforms` per-library at collection time under `--target unix-port` and deselects items for libraries whose platforms list excludes the active `--runtime`.  Release-automation helpers in `scripts/run.py` read the same key for publish gates.  Python 3.11+ includes `tomllib` in the stdlib, so no new dependency is required.

## Consequences

- Existing libraries that target all three runtimes need no change — the default covers them.
- Libraries that are platform-restricted add a one-line table to their `pyproject.toml`.
- Release automation checks the platforms list before publishing to each channel.
- The MP/CP unix-port pytest lane deselects libraries not targeting the active runtime, applied by the `chumicro-pytest-device` plugin at collection time.
- Support packages (under `support/`) are workspace-internal and not published, so the platforms key is irrelevant for them unless they need to be tested against a specific runtime.
