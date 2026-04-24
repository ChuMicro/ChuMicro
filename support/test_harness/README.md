# chumicro-test-harness

A very small test runner and cross-runtime orchestrator for ChuMicro libraries.

This package is intentionally tiny. It is meant to complement host-side `pytest`, not replace it.

## Current manual workflow

The cross-runtime test path uses:

- `support/test_harness/src/chumicro_test_harness/runner.py` — lightweight runner
- `support/test_harness/src/chumicro_test_harness/discovery.py` — test discovery and orchestration
- `support/test_harness/src/chumicro_test_harness/assertions.py` — cross-runtime assertion helpers (`raises()`)
- `libraries/*/tests/test_*.py` (cross-runtime tests — no `import pytest`; files ending in `_pytest.py` are skipped)
- `support/test_harness/run_cross_runtime.py` — entry point (thin bootstrapper)

Today this is wired through `scripts/run.py` for local compatibility evaluation and required CI jobs.

### CPython cross-runtime run

```zsh
cd /path/to/chumicro
python support/test_harness/run_cross_runtime.py
```

### MicroPython Unix-port cross-runtime run

```zsh
cd /path/to/chumicro
python scripts/run.py prepare-micropython
python scripts/run.py test-micropython
```

If no explicit binary is given, `scripts/run.py` first tries the repo-local prepared runtime under `.tools/`, then a `micropython` executable on `PATH`, and otherwise triggers the repo-managed prepare step automatically.  To override, pass `--micropython-binary /path/to/binary`.

### CircuitPython unix-port evaluation run

```zsh
cd /path/to/chumicro
python scripts/run.py prepare-circuitpython
python scripts/run.py test-circuitpython
```

If no explicit binary is given, `scripts/run.py` first tries the repo-local prepared runtime under `.tools/`, then a `circuitpython` executable on `PATH`, and otherwise triggers the repo-managed prepare step automatically.  To override, pass `--circuitpython-binary /path/to/binary`.

In this workspace on macOS, the pinned upstream `10.1.4` unix-port build completes and the cross-runtime unit tests pass under both MicroPython and CircuitPython unix-port interpreters.  Both runtime compatibility checks are required CI status checks.

### Combined host + runtime run

```zsh
cd /path/to/chumicro
python scripts/run.py test-all-runtimes
```

This runs the current verified CPython host test suite, prepares the repo-local runtimes if needed, and then runs the MicroPython and CircuitPython cross-runtime test paths.

## Device testing on real boards

Real-board execution is now wired through `python scripts/run.py test-libraries-functional` and the pytest device plugin used by IDE play buttons for `functional_tests/`.

### Local config files

Run this once to generate local starter files if they do not already exist:

```zsh
python scripts/run.py setup
```

That creates two gitignored files:

- `devices.yml` — board registry plus the `defaults:` section used by bare `test-libraries-functional` runs and IDE play buttons
- `device-config.yml` — shared environment data (WiFi, MQTT, NTP, and similar settings)

### CLI examples

```zsh
# Run the defaults-backed target set from devices.yml
python scripts/run.py test-libraries-functional

# One runtime only
python scripts/run.py test-libraries-functional --runtime micropython --library timing

# Both runtimes using defaults-backed device IDs
python scripts/run.py test-libraries-functional --runtime both --library timing

# Override a specific board selection
python scripts/run.py test-libraries-functional --micropython-device sample-mp-board --library timing

# Scope to a file (filename substring)
python scripts/run.py test-libraries-functional --library timing --file test_heartbeat

# Scope to a function (function-name substring)
python scripts/run.py test-libraries-functional --library timing --function heartbeat_fires

# Force flash deployment for this run
python scripts/run.py test-libraries-functional --library timing --deploy-mode flash
```

### IDE / pytest integration

Normal host-side pytest discovery ignores `functional_tests/`. When you explicitly target a `functional_tests/` file, directory, or function from an IDE, `scripts/pytest_device.py` intercepts that target and runs it on the board(s) selected by `devices.yml`.

If `devices.yml` does not exist yet, the run is skipped with a message telling you to run setup.

See `docs/contributing/device-testing.md`, Decision 0027, and `plans/workstreams/device-validation.md` for the full workflow and current status.
