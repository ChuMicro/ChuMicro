# chumicro-test-harness

A very small test runner intended for `device_tests/` on MicroPython and CircuitPython.

This runner is intentionally tiny. It is meant to complement host-side `pytest`, not replace it.

## Current manual workflow

The first checked-in compatibility smoke path uses:

- `support/test_harness/src/chumicro_test_harness/runner.py`
- `libraries/timing/device_tests/test_heartbeat_ticks.py`
- `ci/run_sample_device_smoke.py`
- `ci/run_sample_device_tests.py` as a backward-compatible wrapper

Today this is wired through `scripts/run.py` for local compatibility evaluation and advisory CI jobs.

### CPython smoke run

```zsh
cd /path/to/chumicro
python ci/run_sample_device_tests.py
```

### MicroPython Unix-port smoke run

```zsh
cd /path/to/chumicro
python scripts/run.py prepare-micropython
python scripts/run.py test-micropython-compat
```

If `MICROPYTHON_BIN` is not set, `scripts/run.py` falls back to the repo-local prepared runtime under `.tools/`, and then to a `micropython` executable on `PATH`.

### CircuitPython unix-port evaluation run

```zsh
cd /path/to/chumicro
python scripts/run.py prepare-circuitpython
python scripts/run.py test-circuitpython-compat
```

If `CIRCUITPYTHON_BIN` is not set, `scripts/run.py` first tries the repo-local prepared runtime under `.tools/`, then a `circuitpython` executable on `PATH`, and otherwise triggers the repo-managed prepare step automatically.

In this workspace on macOS, the pinned upstream `10.1.4` unix-port build now completes and the shared timing smoke runner passes under both MicroPython and CircuitPython unix-port interpreters.

Here, **advisory** means the runtime CI jobs still run and still report real pass/fail results, but they do not fail the overall GitHub Actions workflow yet because the workflow marks them with `continue-on-error: true`.

### Combined host + runtime smoke run

```zsh
cd /path/to/chumicro
python scripts/run.py test-runtime-matrix
```

This runs the current verified CPython host test suite, prepares the repo-local runtimes if needed, and then runs the MicroPython and CircuitPython device-test smoke paths.

## Device registration

Real-board execution is still manual-only. Use `devices.example.yml` as the starting point for your local `devices.yml` file. Keep `devices.yml` out of version control.

