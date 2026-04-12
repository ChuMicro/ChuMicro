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
python scripts/run.py test-micropython-compatibility
```

If no explicit binary is given, `scripts/run.py` first tries the repo-local prepared runtime under `.tools/`, then a `micropython` executable on `PATH`, and otherwise triggers the repo-managed prepare step automatically.  To override, pass `--micropython-binary /path/to/binary`.

### CircuitPython unix-port evaluation run

```zsh
cd /path/to/chumicro
python scripts/run.py prepare-circuitpython
python scripts/run.py test-circuitpython-compatibility
```

If no explicit binary is given, `scripts/run.py` first tries the repo-local prepared runtime under `.tools/`, then a `circuitpython` executable on `PATH`, and otherwise triggers the repo-managed prepare step automatically.  To override, pass `--circuitpython-binary /path/to/binary`.

In this workspace on macOS, the pinned upstream `10.1.4` unix-port build completes and the cross-runtime unit tests pass under both MicroPython and CircuitPython unix-port interpreters.  Both runtime compatibility checks are required CI status checks.

### Combined host + runtime run

```zsh
cd /path/to/chumicro
python scripts/run.py test-runtime-matrix
```

This runs the current verified CPython host test suite, prepares the repo-local runtimes if needed, and then runs the MicroPython and CircuitPython cross-runtime test paths.

## Device registration

Real-board execution is being built out as Milestone 3 (Decision 0027).

- Copy `devices.example.yml` to `devices.yml` and fill in your board details.
- Copy `device-config.example.yml` to `device-config.yml` and fill in WiFi credentials and other test environment settings.
- Keep both files out of version control — they are gitignored.

Once transport tooling is implemented:

```zsh
# Run all functional tests on all configured devices
python scripts/run.py test-device

# Target a specific runtime and library
python scripts/run.py test-device --runtime micropython --library timing

# Target a specific device and test
python scripts/run.py test-device --device sample-mp-board --test test_heartbeat_ticks
```

See Decision 0027 and `plans/workstreams/device-validation.md` for the full design.
