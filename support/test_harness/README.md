# chumicro-test-harness

A very small test runner and cross-runtime orchestrator for ChuMicro libraries.

This package is intentionally tiny.  It is meant to complement host-side `pytest`, not replace it.

## What it provides

- `chumicro_test_harness.runner` — lightweight runner.
- `chumicro_test_harness.discovery` — test discovery and orchestration.
- `chumicro_test_harness.assertions` — cross-runtime assertion helpers (`raises()`, `skip()`).

The harness is what powers cross-runtime unit tests: files under `libraries/*/tests/test_*.py` that don't `import pytest` are picked up and run on whichever interpreter the harness was launched with (CPython, MicroPython unix-port, CircuitPython unix-port).  Files ending in `_pytest.py` are skipped — those are CPython-only and run under host-side `pytest`.

## CPython cross-runtime run

From a checkout root that contains `libraries/<name>/tests/`:

```zsh
python support/test_harness/run_cross_runtime.py
```

## MicroPython unix-port cross-runtime run

```zsh
python -m chumicro_test_harness.runner --interpreter micropython
```

If no explicit binary is given, the runner first tries a workspace-prepared interpreter under `.tools/`, then a `micropython` executable on `PATH`.  To override, pass `--micropython-binary /path/to/binary`.

## CircuitPython unix-port run

```zsh
python -m chumicro_test_harness.runner --interpreter circuitpython
```

Same fallback rules — workspace-prepared `.tools/` interpreter, then `PATH`, then `--circuitpython-binary /path/to/binary` to override.

The harness currently runs against the pinned upstream `10.x` CircuitPython unix-port build; both runtime compatibility checks are part of the workspace's standard CI gates.

## Combined host + runtime run

The full cross-runtime sweep (CPython host tests + both unix-port runtime tests) runs as a single `chumicro-workspace` command in the workspace dispatcher; standalone use of this package typically invokes the runner directly per the sections above.

## Device testing on real boards

Real-board execution does not go through this package — it goes through `chumicro-pytest-device`, the pytest plugin that stages source onto a board and runs `functional_tests/` in the device runtime.  IDE play buttons for `functional_tests/` files use the same plugin.

The test harness shapes the on-device test environment (the `chumicro_test_harness.skip()` primitive, `__chumicro_features__` markers, the `assertions.raises` helper) so the same test sources work both under unix-port harness runs and under `pytest-device` board runs.

## Skipping tests loudly

Use `chumicro_test_harness.skip(reason)` when a runtime feature isn't present (e.g. UDP on a runtime that lacks it).  Bare `if cond: return` is a silent skip — it reads as PASS, hiding broken tests.  The harness's `skip()` raises a sentinel exception the runner classifies as SKIP with the given reason, so missing features stay visible.
