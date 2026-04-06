# chumicro-test-harness

A very small test runner and cross-runtime orchestrator for Chumicro libraries.

This package is intentionally tiny. It is meant to complement host-side `pytest`, not replace it.

## Current manual workflow

The cross-runtime test path uses:

- `support/test_harness/src/chumicro_test_harness/runner.py` — lightweight runner
- `support/test_harness/src/chumicro_test_harness/discovery.py` — test discovery and orchestration
- `libraries/*/tests/test_*.py` (cross-runtime tests — no `import pytest`)
- `support/test_harness/run_cross_runtime.py` — entry point (thin bootstrapper)

Today this is wired through `scripts/run.py` for local compatibility evaluation and advisory CI jobs.

### CPython cross-runtime run

```zsh
cd /path/to/chumicro
python support/test_harness/run_cross_runtime.py
```

### MicroPython Unix-port cross-runtime run

```zsh
cd /path/to/chumicro
python scripts/run.py prepare-micropython
python scripts/run.py test-micropython-compatibility
```

If `MICROPYTHON_BIN` is not set, `scripts/run.py` falls back to the repo-local prepared runtime under `.tools/`, and then to a `micropython` executable on `PATH`.

### CircuitPython unix-port evaluation run

```zsh
cd /path/to/chumicro
python scripts/run.py prepare-circuitpython
python scripts/run.py test-circuitpython-compatibility
```

If `CIRCUITPYTHON_BIN` is not set, `scripts/run.py` first tries the repo-local prepared runtime under `.tools/`, then a `circuitpython` executable on `PATH`, and otherwise triggers the repo-managed prepare step automatically.

In this workspace on macOS, the pinned upstream `10.1.4` unix-port build now completes and the cross-runtime unit tests pass under both MicroPython and CircuitPython unix-port interpreters.

Here, **advisory** means the runtime CI jobs still run and still report real pass/fail results, but they do not fail the overall GitHub Actions workflow yet because the workflow marks them with `continue-on-error: true`.

### Combined host + runtime run

```zsh
cd /path/to/chumicro
python scripts/run.py test-runtime-matrix
```

This runs the current verified CPython host test suite, prepares the repo-local runtimes if needed, and then runs the MicroPython and CircuitPython cross-runtime test paths.

## Device registration

Real-board execution is still manual-only. Use `devices.example.yml` as the starting point for your local `devices.yml` file. Keep `devices.yml` out of version control.

