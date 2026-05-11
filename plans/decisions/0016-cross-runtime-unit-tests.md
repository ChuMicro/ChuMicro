# Decision 0016: Cross-runtime unit tests

Status: `accepted`
Date: `2026-04-03`
Related: Decision 0006 (supersedes), Decision 0010 (testability), Decision 0027 (device tests — `chumicro-pytest-device` plugin), Decision 0058 (loud-skip primitive + `__chumicro_runtimes__` / `__chumicro_features__` markers)

## Context

CPython-hosted pytest gives full unit-test coverage of the libraries, but the runtimes that actually matter for the shipped behavior — MicroPython and CircuitPython — were previously exercised only by tiny import-level smoke checks (Decision 0006).  The libraries are intended to run on all three runtimes (CPython, MP unix-port, CP unix-port) using constructor-injected fakes (Decision 0010), so the test pyramid needs a middle tier that runs the same logic checks under MP and CP — not just on real devices, and not just at the import level.

The directory shape inherited from the smoke-check era — a per-library `device_tests/` — read ambiguously: the files lived there for the unix-port smoke runner, not because they required real hardware.  A rename was due in the same change.

## Decision

### Directory rename

Each library has three test directories with clear, non-overlapping purposes:

| Directory | Runner | Where it runs | Purpose |
|---|---|---|---|
| `tests/` | pytest — CPython directly; MP/CP unix-ports via `chumicro-pytest-device`'s `UnixPortBackend` | CPython, MP/CP unix-ports, real devices | Logic verification with fakes and plain asserts |
| `functional_tests/` | pytest via `chumicro-pytest-device`'s `DeviceBackend` | Real hardware only | Tests requiring real I/O: GPIO, WiFi, real-time |

`tests/` keeps the standard Python name.  `device_tests/` is renamed to `functional_tests/`.

### Cross-runtime portability rule

Unit test files that need to run on MicroPython/CircuitPython must not `import pytest`.  They use:

- Constructor-injected fakes (Decision 0010)
- Plain `assert` statements
- `raises()` from the test harness for exception checking

The `import pytest` line is the portability boundary, enforced by file-name convention (below): the `chumicro-pytest-device` plugin's unix-port collection path excludes any `test_*_pytest.py` file, so pytest-using tests never reach the MP/CP worker.  Cross-runtime files land in worker subprocesses that have no pytest available.

### File naming convention

Within `tests/`, cross-runtime and CPython-only tests coexist:

- `test_heartbeat.py` — cross-runtime (no pytest import, uses fakes)
- `test_ticks.py` — cross-runtime (arithmetic, masking, overflow)
- `test_ticks_pytest.py` — CPython-only (uses monkeypatch, pytest.raises)

Cross-runtime is the default.  Only files that require pytest get the `_pytest` suffix.

### Pytest as the single front-running test surface

Pytest is the only contributor-facing test command across all three runtimes.  Bare `pytest libraries/<name>/tests/` runs the CPython lane (root [`pyproject.toml`](../../pyproject.toml) + [`conftest.py`](../../conftest.py) handle import-mode + `functional_tests/` deselection).  `pytest libraries/<name>/tests/ --target unix-port --runtime micropython` (or `circuitpython`) runs the same files under the unix-port binary, with `chumicro-pytest-device` claiming the `test_*.py` collection (excluding `*_pytest.py`), dispatching each file through `UnixPortBackend`, parsing the worker's harness-format output back into pytest items, and applying the `[tool.chumicro].platforms` filter so libraries that don't target a runtime get deselected rather than run.

`scripts/run.py test-micropython` / `test-circuitpython` / `test-all-runtimes` are thin wrappers — they resolve / auto-build the unix-port binary via `prepare-{micropython,circuitpython}` and delegate to the pytest invocation above.  IDE play buttons that target a single test function under the `--target unix-port` profile run through the same plugin path; nothing in the test-discovery layer is bespoke to `scripts/run.py`.

### Test harness role under the plugin

[`support/test_harness/run_cross_runtime.py`](../../support/test_harness/run_cross_runtime.py) retains worker mode only — one invocation per test file as `<binary> support/test_harness/run_cross_runtime.py --worker <test_file>`, called by `UnixPortBackend`.  The harness's `chumicro_test_harness.discovery` module exposes `run_one_file`, `setup_source_paths`, `discover_source_roots`, and `_exec_as_namespace`; the prior manager-mode entry points (`run_all`, `_run_all_isolated`, `_run_all_inline`, `discover_tests`) were removed when the plugin took over orchestration.

Cross-runtime test bodies import two helpers directly from `chumicro_test_harness`: `raises()` (a small context manager that checks for a specific exception type — the only pytest API the no-pytest-import rule would otherwise lose) and `skip()` (the loud-skip primitive — see [Decision 0058](0058-test-skips-must-be-loud.md)).  `monkeypatch` tests are inherently CPython-only: they simulate runtimes on CPython, which is pointless on the real runtime, so they get the `_pytest.py` suffix and stay in the CPython lane.

## Alternatives considered

- **Three directories** (unit, compat, functional) — rejected; the compat tier would duplicate unit tests without pytest conveniences.
- **Full pytest reimplementation** for MP/CP — rejected; heavy lift with diminishing returns.  The subset needed (asserts + raises) is tiny.
- **All tests in one directory with skip decorators** — rejected; requires a decorator infrastructure and doesn't give clear intent.
- **Keep the lightweight harness as a peer front-running entry point alongside pytest** — rejected when `chumicro-pytest-device` grew a `UnixPortBackend`.  Two parallel orchestration layers cost contributor mental model + IDE configuration churn for no win; the harness's worker mode covers the per-file execution the plugin needs, and removing the manager mode deleted a duplicate test-discovery path.

## Consequences

- Supersedes Decision 0006 (import-free smoke runner).  The smoke runner now runs real unit tests, not just import checks.
- Decision 0003 (test pyramid) gains a new middle tier: unit tests on MP/CP unix-ports.
- Scaffold (`new-library`) creates `tests/` and `functional_tests/` instead of `tests/` and `device_tests/`.
- Pytest is the single front-running test surface for every runtime.  IDE play buttons reach the unix-port lane via `--target unix-port`, the same plugin path used for on-device functional tests.
- `support/test_harness/run_cross_runtime.py` is invoked per-file by the plugin's `UnixPortBackend`; `scripts/run.py` never invokes it directly.

## Open issue: on-device import destructiveness

During early on-device testing, importing files directly from the workspace filesystem on CircuitPython and MicroPython was observed to delete file contents when build errors occurred.  This means on-device test execution (including `functional_tests/`) will need to **copy test files to a staging area** before running them, rather than importing directly from the workspace tree.  This applies to examples too (see Decision 0013).  The staging mechanism is defined in [Decision 0027](0027-device-testing-infrastructure.md) — the host generates a bootstrap script and staging tree in `.scratch/device-staging/`, and for MicroPython, `mpremote mount` avoids writing to device flash entirely.
