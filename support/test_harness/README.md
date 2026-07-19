# chumicro-test-harness

A small cross-runtime test runner for ChuMicro libraries.  It complements host-side `pytest` rather than replacing it, and it installs automatically through the `[test]` extra of any chumicro library (`pip install chumicro-mqtt[test]`).

## What it provides

| Module | What it exports |
|---|---|
| `chumicro_test_harness.runner` | `run_module(module, name_filter=None)` |
| `chumicro_test_harness.discovery` | `discover_source_roots`, `setup_source_paths`, `run_one_file` |
| `chumicro_test_harness.assertions` | `raises` (pytest-shaped context manager) |
| `chumicro_test_harness.skip` | `skip(reason)` |

Top-level re-exports: `from chumicro_test_harness import raises, skip, run_module, run_one_file`.

The harness powers cross-runtime unit tests.  A library's `tests/test_*.py` files (excluding `*_pytest.py`) execute under MicroPython unix-port, CircuitPython unix-port, and CPython through normal `pytest` collection.  Test files stay `import pytest`-free so the same sources run unchanged on every runtime.

## How tests reach the harness

The pytest plugin `chumicro-pytest-device` owns discovery and orchestration.  Two activation paths:

- `pytest <library>/tests --target unix-port --runtime micropython`: the plugin spawns one `<micropython-binary> run_cross_runtime.py --worker <test_file>` subprocess per file.  The worker `exec()`s the file as a module, calls `run_module`, and prints `PASS` / `FAIL` / `SKIP` / `HEAP` / `SUMMARY` lines back to the host.
- `pytest <library>/functional_tests/`: the plugin routes through the `chumicro-deploy` transport instead, staging source onto a real board and running it there.

The chumicro workspace ships CLI wrappers that resolve the unix-port binary (workspace-prepared `.tools/` build first, then `PATH`), auto-build it on first use, and delegate to the pytest invocation above.  Pass `--micropython-binary <path>` / `--circuitpython-binary <path>` to override.

## Device testing on real boards

Real-board execution goes through `chumicro-pytest-device`, the pytest plugin that stages source onto a board and runs `functional_tests/` in the device runtime.  IDE play buttons for `functional_tests/` files use the same plugin.

The test harness shapes the on-device test environment (the `chumicro_test_harness.skip()` primitive, `__chumicro_features__` markers, the `assertions.raises` helper) so the same test sources work both under unix-port harness runs and under on-device runs.

## Skipping tests loudly

Use `chumicro_test_harness.skip(reason)` when a runtime feature isn't present (e.g. UDP on a runtime that lacks it).  Bare `if cond: return` is a silent skip: it reads as PASS and hides broken tests.  The harness's `skip()` raises a sentinel exception the runner classifies as SKIP with the given reason, so missing features stay visible.
