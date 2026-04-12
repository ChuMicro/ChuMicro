# Decision 0027: Device testing infrastructure

Status: `accepted`
Date: `2026-04-12`
Related: Decision 0003, Decision 0016, Decision 0015

## Context

Milestone 3 requires deploying and validating code on real MicroPython and CircuitPython boards.  The workspace has host-side pytest, cross-runtime unix-port tests, and `functional_tests/` directories per library — but no transport layer, no device configuration schema, and no way to run functional tests on hardware from the IDE or command line.

MicroPython has `mpremote` (official, well-maintained, pip-installable).  CircuitPython has no equivalent — options are CIRCUITPY USB copy, Web Workflow REST API, and serial raw-paste-mode execution via pyserial.

## Decision

### Configuration

Two user-local config files, both gitignored:

- **`devices.yml`** — device registry (board connections, serial addresses, runtime type).  Template: `devices.example.yml`.
- **`device-config.yml`** — shared test environment (WiFi SSID/password, MQTT broker, etc.).  Template: `device-config.example.yml`.

Environment variable overrides: `CHUMICRO_DEVICES` and `CHUMICRO_DEVICE_CONFIG` for CI.

A `scripts/device_config.py` module loads, validates, and exposes the config to `run.py` and the transport layer.

### Transport protocol (duck-typed)

Transport implementations live in `support/device_transport/`.  The protocol is documented, not enforced by a base class:

```
connect() -> None
stage(source_dirs, test_files, harness_src) -> None
execute(bootstrap_script) -> str   # returns captured stdout
reset() -> None
disconnect() -> None
```

### MicroPython transport

Uses `mpremote` (subprocess).  Two modes:

- **Mount mode** (default): `mpremote connect <addr> mount <staging_dir> run <bootstrap>` — streams files from host, no flash wear, fast iteration.
- **Copy mode** (fallback): `mpremote connect <addr> fs cp -r <staged_tree> :` then `run` — for boards where mount is unreliable.

### CircuitPython transport

Uses `pyserial` to drive raw REPL / raw paste mode:

1. Connect to serial port, interrupt running code (Ctrl-C × 2).
2. Enter raw REPL (Ctrl-A).
3. Paste bootstrap script via raw paste mode (Ctrl-E, supported in CP 7+).
4. Capture output until `SUMMARY` line or timeout.

File staging options, in priority order:

1. **Inline paste** — for small functional tests, paste library source and test code directly.  Limited by device RAM.
2. **Web Workflow REST API** — for WiFi-enabled boards running CP 8+, `PUT /fs/` to upload files, then execute via serial.
3. **CIRCUITPY USB copy** — copy to mounted drive.  Unreliable for automation; defer to later phase.

### Bootstrap and harness

The host generates a bootstrap `.py` file into `.scratch/device-staging/` that:

1. Sets up `sys.path` to find staged library code and the harness.
2. Injects environment config (WiFi SSID, etc.) into a module-level dict.
3. Imports `chumicro_test_harness.runner.run_module`.
4. Loads the target test file via `exec()` (same pattern as `discovery._exec_as_namespace`).
5. Calls `run_module(namespace)` and prints the exit code.

The staging directory mirrors the workspace layout so `sys.path` setup is identical to the cross-runtime harness.

### Harness enhancement: test name filter

Add an optional `name_filter` parameter to `runner.run_module(module, name_filter=None)`.  When set, only `test_*` functions whose name contains the filter string are executed.  This enables single-test execution from the IDE.

### run.py integration

Replace the placeholder `test-device` command with real orchestration:

```
python scripts/run.py test-device
    --runtime micropython|circuitpython   # filter devices by runtime
    --device <id>                         # target specific device
    --library <name>                      # limit to one library
    --test <name>                         # filter to test file or function name
```

Flow: load config → select transport → for each library, stage `src/` + `functional_tests/` + harness → run each test file → parse output → report summary.

### IDE integration

A pytest conftest or plugin intercepts `functional_tests/` collection when `CHUMICRO_DEVICE_RUNTIME` is set in the environment.  Each collected `test_*` function becomes a pytest item that stages, executes on device, parses output, and reports as pytest pass/fail.

- **PyCharm:** Set `CHUMICRO_DEVICE_RUNTIME=micropython` (or `circuitpython`) in a run configuration template.  Play buttons work at file and function level.
- **VSCode:** Same env var in `settings.json` or `.env`.

### Output parsing

A `result_parser.py` module parses the harness's structured output (`PASS`, `FAIL`, `SKIP`, `SUMMARY`, `HEAP` lines) into typed result objects.  This is the contract between device execution and host reporting.

## Alternatives considered

- **pytest-embedded** (Espressif's pytest plugin for ESP-IDF) — rejected; tightly coupled to ESP-IDF, not MicroPython/CircuitPython.
- **Run pytest on device** — rejected per Decision 0003; pytest footprint is too large for constrained boards.
- **CIRCUITPY USB as primary CP transport** — rejected; unreliable for automation (filesystem sync timing, macOS ejection issues, not available on non-USB boards like ESP32).
- **Build a full REPL library for CircuitPython** — deferred; raw paste mode via pyserial is sufficient for functional test execution.  A dedicated REPL library is a future project if the serial transport proves too limited.

## Consequences

- `mpremote` and `pyserial` are added to `requirements-dev.txt`.
- `device-config.yml` and `devices.yml` must be in `.gitignore`.
- The harness `runner.run_module` gains a backward-compatible `name_filter` parameter.
- `test-device` becomes a real command instead of a placeholder.
- IDE play buttons work for functional tests when the device runtime env var is set.
- Transport implementations are workspace-internal (in `support/`), not published libraries.
- Decision 0016's staging requirement is addressed by the bootstrap/staging mechanism.

