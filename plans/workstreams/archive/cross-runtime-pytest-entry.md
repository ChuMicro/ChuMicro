# Cross-runtime pytest entry — workstream

Status: closed
Started: 2026-05-11
Closed: 2026-05-11

Wire a pytest entry point for the MicroPython / CircuitPython unix-port unit-test path so IDE play buttons can target it at file and function granularity — and so the workspace has one front-running test surface (pytest) for every runtime.

## Why

Today CPython unit tests run via bare pytest, on-device functional tests run via `chumicro-pytest-device` (also pytest), but the unix-port unit-test path is only reachable through `python scripts/run.py test-micropython` / `test-circuitpython` / `test-all-runtimes`.  Those invoke `<binary> support/test_harness/run_cross_runtime.py` directly — no pytest seam.  IDE play buttons can't aim at the unix-port path; the layering reads asymmetric to a contributor.

## Design

Extend `chumicro-pytest-device` with a unix-port subprocess backend alongside its existing device-transport backend.  Reuses the AST-based collection, harness output parser, runtime markers, and PR-summary collector.  One mental model: `--runtime` picks which Python; new `--target` picks which backend (device serial vs. unix-port subprocess).

### Flag rename — drop `chumicro-` prefix

Pre-existing flags `--chumicro-runtime` / `--chumicro-micropython-device` / `--chumicro-circuitpython-device` / `--chumicro-deploy-mode` / `--chumicro-pr-summary` / `--chumicro-pr-summary-command` lose the prefix.  They live in a named pytest option group anyway; the prefix was defensive but ugly.  Zero shipped consumers — workspace + docs are the only callers, all renamed in this workstream.

### New flags

- `--target {device,unix-port}` — default `device` (preserves existing IDE / device behavior).
- `--micropython-binary <path>` — unix-port MP binary override.
- `--circuitpython-binary <path>` — unix-port CP binary override.

### Backend abstraction

`DeviceRuntimeItem._ensure_batch_result` calls through a `Backend` interface.  `DeviceBackend` wraps today's transport+stage+execute path.  New `UnixPortBackend` resolves the runtime binary (override → `.tools/<runtime>-<version>/` → PATH), spawns `<binary> support/test_harness/run_cross_runtime.py --worker <test_file>`, captures stdout, hands to existing `parse_output()`.

### Collection

When `--target unix-port` is set, plugin also claims `libraries/<name>/tests/test_*.py` (excluding `*_pytest.py`).  `pytest_pycollect_makemodule` returns a no-import stub for these paths only when the unix-port target is active — default `pytest` invocation stays unchanged so plain CPython unit tests run through bare pytest as today.

### Platform filtering

Each library declares `[tool.chumicro].platforms` in its `pyproject.toml`.  When `--target unix-port --runtime micropython`, the plugin reads each test file's library `pyproject.toml` and deselects items for libraries whose platforms list excludes `micropython`.  Same rule today's `scripts/run.py` applies via `filter_by_platform`; moved into the plugin so direct IDE invocations get the right behavior too.

### Coverage gate

Per-library `pyproject.toml` `addopts` includes `--coverage-threshold 94` for CPython runs.  Under `--target unix-port` no host code executes the test bodies, so coverage reports 0%.  Plugin disables coverage args in `pytest_configure` when the target is unix-port.

### scripts/run.py collapse

`test-libraries-functional` already invokes pytest.  Once the plugin handles unix-port too:

- `test-micropython` → `pytest libraries/ --target unix-port --runtime micropython`
- `test-circuitpython` → `pytest libraries/ --target unix-port --runtime circuitpython`
- `test-all-runtimes` keeps its CPython-first + parallel-phases shape; each phase becomes a pytest invocation.

Delete: `_test_runtime_compat`, `COMPAT_SCRIPT` constant.  Strip manager-mode entry in `run_cross_runtime.py`.  Delete `run_all` / `_run_all_isolated` / `_run_all_inline` / `discover_tests` from `chumicro_test_harness.discovery`.  Keep: `run_one_file`, `setup_source_paths`, `discover_source_roots`, `_exec_as_namespace` — still needed by worker mode + pytest-device plugin's existing on-device path.

## Phases

1. **Rename flags** — drop `chumicro-` prefix across plugin, plugin tests, `scripts/run.py`, `workbench/pytest-device/README.md`, `docs/contributing/{device-testing,cheat-sheet}.md`, ADR 0047, functional-test docstrings.  Single commit.  Tests stay green.
2. **Backend abstraction** — extract `Backend` protocol; existing transport path becomes `DeviceBackend`.  No behavior change.  Plugin tests stay green.
3. **`UnixPortBackend` + new flags + collection** — binary resolution helper, subprocess executor, `--target` flag, `--{micropython,circuitpython}-binary` flags, `libraries/<name>/tests/` collection path, `[tool.chumicro].platforms` filter, coverage-arg suppression.  New plugin tests cover the new path.
4. **run.py collapse + discovery cleanup** — rewrite `test-micropython` / `test-circuitpython` / `test-all-runtimes` as pytest wrappers.  Delete manager-mode code from `run_cross_runtime.py` + `discovery.py`.  Update `support/test_harness/README.md`.
5. **Docs + IDE configs + close** — update `docs/contributing/` workflow docs; `scripts/run.py sync-ide` regenerates PyCharm run configurations + VS Code launch entries for the new `--target unix-port` profile; move next-up entry to `## Done (recent)`.

## Validation

End-to-end: `python scripts/run.py test-all-runtimes` produces the same pass / fail count as before, but routes through pytest.  IDE play-button on a single `test_*` function in `libraries/timing/tests/test_heartbeat.py` with the unix-port run-configuration runs that one function under the MP unix-port and reports back.  Bare `pytest libraries/timing/tests/` (no `--target`) stays the CPython lane, byte-for-byte unchanged.

## Out of scope

- Coverage instrumentation under unix-port (CPython remains the coverage-of-record source).
- `--no-isolate` exposure (per-file worker is the right default).
- `--target both` (run unix-port AND on-device for the same test file).  Add later if there's a forcing function.
