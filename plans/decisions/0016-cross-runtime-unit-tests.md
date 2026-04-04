# Decision 0016: Cross-runtime unit tests

Status: `accepted`
Date: `2026-04-03`

## Context

The compat smoke tests (`test-micropython-compat`, `test-circuitpython-compat`) previously ran only `device_tests/` — a tiny set of import-level smoke checks (Decision 0006).  The user wants unit tests to run on all three runtimes (CPython, MicroPython unix-port, CircuitPython unix-port) using constructor-injected fakes, not just on CPython via pytest.

Meanwhile, the existing `device_tests/` directory name was ambiguous — it contained tests runnable on unix-ports, not necessarily on real devices.

## Decision

### Directory rename

Each library has three test directories with clear, non-overlapping purposes:

| Directory | Runner | Where it runs | Purpose |
|---|---|---|---|
| `unit_tests/` | pytest (CPython), lightweight harness (MP/CP) | CPython, MP/CP unix-ports, real devices | Logic verification with fakes and plain asserts |
| `functional_tests/` | lightweight harness | Real hardware only | Tests requiring real I/O: GPIO, WiFi, real-time |

`tests/` is renamed to `unit_tests/`.  `device_tests/` is renamed to `functional_tests/`.

### Cross-runtime portability rule

Unit test files that need to run on MicroPython/CircuitPython must not `import pytest`.  They use:

- Constructor-injected fakes (Decision 0010)
- Plain `assert` statements
- `raises()` from the test harness for exception checking

The `import pytest` line is the automatic portability boundary.  The lightweight harness tries to import each test file; if it fails (because `import pytest` is unavailable on MP/CP), the file is logged as `SKIP` and the harness continues.  No naming convention or decorator is needed.

### File naming convention

Within `unit_tests/`, cross-runtime and CPython-only tests coexist:

- `test_heartbeat.py` — cross-runtime (no pytest import, uses fakes)
- `test_ticks_cross.py` — cross-runtime portion of ticks tests
- `test_ticks_pytest.py` — CPython-only (uses monkeypatch, pytest.raises)

The `_pytest` suffix signals "CPython-only."  The `_cross` suffix signals "cross-runtime."  Files without a suffix are cross-runtime by default (encouraged).

### Smoke runner scope change

The compat tasks (`test-micropython-compat`, `test-circuitpython-compat`) now run `unit_tests/` through the lightweight harness — not `functional_tests/`.  `functional_tests/` is a separate run type for real devices only.

### Test harness additions

The test harness gains a `raises()` context manager (~15 lines) that checks for a specific exception type.  This is the only pytest API that cross-runtime tests need.  `monkeypatch` tests are inherently CPython-only — they simulate runtimes on CPython, which is pointless on the real runtime.

## Alternatives considered

- **Three directories** (unit, compat, functional) — rejected; the compat tier would duplicate unit tests without pytest conveniences.
- **Full pytest reimplementation** for MP/CP — rejected; heavy lift with diminishing returns.  The subset needed (asserts + raises) is tiny.
- **All tests in one directory with skip decorators** — rejected; requires a decorator infrastructure and doesn't give clear intent.

## Consequences

- Supersedes Decision 0006 (import-free smoke runner).  The smoke runner now runs real unit tests, not just import checks.
- Decision 0003 (test pyramid) gains a new middle tier: unit tests on MP/CP unix-ports.
- Scaffold (`new-library`) creates `unit_tests/` and `functional_tests/` instead of `tests/` and `device_tests/`.
- Existing tests require a one-time split and rename.

