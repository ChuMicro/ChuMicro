# chumicro-test-harness

A small cross-runtime test runner for ChuMicro libraries — internal to the mono-repo (not on PyPI), and meant to complement host-side `pytest` rather than replace it.

## What it provides

| Module | What it exports |
|---|---|
| `chumicro_test_harness.runner` | `run_module(module, name_filter=None)` |
| `chumicro_test_harness.discovery` | `discover_source_roots`, `discover_tests`, `run_all`, `run_one_file` |
| `chumicro_test_harness.assertions` | `raises` (pytest-shaped context manager) |
| `chumicro_test_harness.skip` | `skip(reason)` |

Top-level re-exports: `from chumicro_test_harness import raises, skip, run_module, run_all`.

The harness powers cross-runtime unit tests.  Files under `libraries/*/tests/test_*.py` are picked up and run on whichever interpreter `run_cross_runtime.py` was launched with (CPython, MicroPython unix-port, CircuitPython unix-port).  Files whose name ends in `_pytest.py` are skipped — those are CPython-only and run under host-side `pytest`.

## CPython cross-runtime run

From the workspace root:

```zsh
python support/test_harness/run_cross_runtime.py [library ...]
```

Positional library names narrow the sweep to a subset; with none given, all libraries run.  Pass `--no-isolate` (before the library list) to share one process across files; the default spawns a fresh subprocess per file so each test starts with a clean heap, mirroring real-board behaviour.

## MicroPython unix-port cross-runtime run

Launch the script under a MicroPython unix-port binary:

```zsh
micropython support/test_harness/run_cross_runtime.py [library ...]
```

The mono-repo ships a CLI wrapper that resolves the binary (workspace-prepared `.tools/` build first, then `PATH`), auto-builds if missing, and accepts a `--micropython-binary /path/to/binary` override.

## CircuitPython unix-port run

Same shape:

```zsh
circuitpython support/test_harness/run_cross_runtime.py [library ...]
```

The mono-repo wrapper has a parallel CircuitPython invocation with `--circuitpython-binary` override.  The harness runs against the pinned upstream 10.x CircuitPython unix-port build; both runtime compatibility checks are part of the standard CI gates.

## Combined host + runtime run

The full cross-runtime sweep (CPython unit tests + both unix-port runtimes) ships as a single mono-repo command that fans out across the three runtimes from the workspace root.

## Device testing on real boards

Real-board execution does not go through this package — it goes through `chumicro-pytest-device`, the pytest plugin that stages source onto a board and runs `functional_tests/` in the device runtime.  IDE play buttons for `functional_tests/` files use the same plugin.

The test harness shapes the on-device test environment (the `chumicro_test_harness.skip()` primitive, `__chumicro_features__` markers, the `assertions.raises` helper) so the same test sources work both under unix-port harness runs and under `pytest-device` board runs.

## Skipping tests loudly

Use `chumicro_test_harness.skip(reason)` when a runtime feature isn't present (e.g. UDP on a runtime that lacks it).  Bare `if cond: return` is a silent skip — it reads as PASS, hiding broken tests.  The harness's `skip()` raises a sentinel exception the runner classifies as SKIP with the given reason, so missing features stay visible.
