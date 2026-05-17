# Decision 0016: Cross-runtime unit tests

Status: `accepted`
Date: `2026-04-03`
Related: Decision 0006 (supersedes), Decision 0010 (testability), Decision 0027 (device tests — `chumicro-pytest-device` plugin), Decision 0058 (loud-skip primitive + `__chumicro_runtimes__` / `__chumicro_features__` markers), Decision 0070 (test-lane markers — replaces this decision's `_pytest` filename convention with in-file markers)

## Context

CPython-hosted pytest gives full unit-test coverage of the libraries, but the runtimes that actually matter for the shipped behavior — MicroPython and CircuitPython — were previously exercised only by tiny import-level smoke checks (Decision 0006).  The libraries are intended to run on all three runtimes (CPython, MP unix-port, CP unix-port) using constructor-injected fakes (Decision 0010), so the test pyramid needs a middle tier that runs the same logic checks under MP and CP — not just on real devices, and not just at the import level.

The directory shape inherited from the smoke-check era — a per-library `device_tests/` — read ambiguously: the files lived there for the unix-port smoke runner, not because they required real hardware.  A rename was due in the same change.

## Decision

### Directory rename

Each library has three test directories with clear, non-overlapping purposes:

| Directory | Runner | Where it runs | Purpose |
|---|---|---|---|
| `tests/` | pytest — CPython directly; MP/CP unix-ports via `chumicro-pytest-device`'s `UnixPortBackend` | CPython + MP/CP unix-ports; real devices for device-lane files only (host-only files stop at the unix-ports — see lane markers below) | Logic verification with fakes and plain asserts |
| `functional_tests/` | pytest via `chumicro-pytest-device`'s `DeviceBackend` | Real hardware only | Tests requiring real I/O: GPIO, WiFi, real-time |

`tests/` keeps the standard Python name.  `device_tests/` is renamed to `functional_tests/`.

### Cross-runtime portability rule

Unit test files that need to run on MicroPython/CircuitPython must not `import pytest`.  They use:

- Constructor-injected fakes (Decision 0010)
- Plain `assert` statements
- `raises()` from the test harness for exception checking

The `import pytest` line is the portability boundary, enforced by an **in-file marker** read AST-only by the `chumicro-pytest-device` plugin — not by the filename.  A pytest-using file declares `__chumicro_runtimes__ = ("cpython",)`; the plugin's unix-port / device-unit collection filters it out by that marker (`_filter_targets_by_marker`), so pytest-using tests never reach the MP/CP worker.  Cross-runtime files land in worker subprocesses that have no pytest available.

### Test-lane markers

Within `tests/`, the lane is declared **in the file**, never inferred from its name (the marker-is-the-contract principle of [Decision 0070](0070-host-only-test-marker.md), mirroring Decision 0037 §2):

- *(no marker)* — cross-runtime device lane: runs on CPython + MP/CP unix-ports **and** real silicon (the default). E.g. `test_heartbeat.py`, `test_ticks.py`.
- `__chumicro_runtimes__ = ("cpython",)` — CPython-only: pytest fixtures / host stdlib unavailable cross-runtime (e.g. `monkeypatch`, `tracemalloc`, loopback `socket`).
- `__chumicro_host_only__ = True` — host lane: runs on CPython + MP/CP unix-ports but never real silicon (drives runtime-specific source through host fakes, asserts off-target behaviour). See [Decision 0070](0070-host-only-test-marker.md).

Cross-runtime device-lane is the default; a file opts down explicitly. Filenames (including the legacy `_pytest` suffix on files that predate the marker, and the `test_{mp,cp}_*` host-lane files) are non-load-bearing human hints — collection never inspects them for lane.

### Class-based tests + the zero-item guard

The cross-runtime harness discovers two shapes, matching pytest's default collection and the on-device runner (`chumicro_test_harness.runner._iter_test_functions`): module-level `def test_*` functions, and `test_*` methods on `class Test*` classes reported as `ClassName.test_method`.  `_parse_test_functions` (host-side AST collection) emits the same qualified-name format the runner produces, so collection items, single-test name filters, and per-item reporting line up between collection and execution.  Class-method discovery was added after the on-device sweep exposed that the host-side parser had been function-only; the ~800 affected class methods now run cross-runtime + on-device as their location implies, and the interim `__chumicro_runtimes__ = ("cpython",)` markers that had pinned them to CPython were reverted.

Two rules guard the lane:

- **No silent zero-item files.**  A device-lane `libraries/<name>/tests/test_*.py` collected for the unix-port / device-unit lane that yields zero discoverable tests (no module-level `def test_*` **and** no `class Test*` method) fails **loudly** at collection (`pytest.Collector.CollectError`, the Decision 0058 "no silent skips" principle at file granularity) — naming the remedy — instead of contributing nothing unnoticed.  A zero now means the file is genuinely pytest-style (fixtures / parametrize / bare `import pytest`).  Marker-excluded files (`__chumicro_runtimes__` / `__chumicro_host_only__`) are filtered before this check, so a declared opt-out is not a guard violation.
- **Genuine pytest-fixture suites declare the CPython lane.**  A suite that needs pytest fixtures / `monkeypatch` / `parametrize` (the `*_pytest.py` files) declares `__chumicro_runtimes__ = ("cpython",)` — explicit, greppable, guard-satisfying.  Class organization alone no longer requires this; only an actual pytest-runtime dependency does.

### Pytest as the single front-running test surface

Pytest is the only contributor-facing test command across all three runtimes.  Bare `pytest libraries/<name>/tests/` runs the CPython lane (root [`pyproject.toml`](../../pyproject.toml) + [`conftest.py`](../../conftest.py) handle import-mode + `functional_tests/` deselection).  `pytest libraries/<name>/tests/ --target unix-port --runtime micropython` (or `circuitpython`) runs the same files under the unix-port binary, with `chumicro-pytest-device` claiming the `test_*.py` collection (excluding `*_pytest.py`), dispatching each file through `UnixPortBackend` (lane filtered by in-file marker, not filename), parsing the worker's harness-format output back into pytest items, and applying the `[tool.chumicro].platforms` filter so libraries that don't target a runtime get deselected rather than run.

`scripts/run.py test-micropython` / `test-circuitpython` / `test-all-runtimes` are thin wrappers — they resolve / auto-build the unix-port binary via `prepare-{micropython,circuitpython}` and delegate to the pytest invocation above.  IDE play buttons that target a single test function under the `--target unix-port` profile run through the same plugin path; nothing in the test-discovery layer is bespoke to `scripts/run.py`.

### Test harness role under the plugin

[`support/test_harness/run_cross_runtime.py`](../../support/test_harness/run_cross_runtime.py) retains worker mode only — one invocation per test file as `<binary> support/test_harness/run_cross_runtime.py --worker <test_file>`, called by `UnixPortBackend`.  The harness's `chumicro_test_harness.discovery` module exposes `run_one_file`, `setup_source_paths`, `discover_source_roots`, and `_exec_as_namespace`; the prior manager-mode entry points (`run_all`, `_run_all_isolated`, `_run_all_inline`, `discover_tests`) were removed when the plugin took over orchestration.

Cross-runtime test bodies import two helpers directly from `chumicro_test_harness`: `raises()` (a small context manager that checks for a specific exception type — the only pytest API the no-pytest-import rule would otherwise lose) and `skip()` (the loud-skip primitive — see [Decision 0058](0058-test-skips-must-be-loud.md)).  `monkeypatch` tests are inherently CPython-only: they simulate runtimes on CPython, which is pointless on the real runtime, so they declare `__chumicro_runtimes__ = ("cpython",)` and stay in the CPython lane.

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
