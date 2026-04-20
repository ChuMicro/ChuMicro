# Device Testing

This guide covers the real-board testing workflow for ChuMicro libraries.

Use it when you want to:

- run `functional_tests/` on a connected MicroPython or CircuitPython board
- understand how `devices.yml` and `device-config.yml` are structured
- use `python scripts/run.py test-device`
- use IDE play buttons for `functional_tests/`

Host-side `tests/` still run through normal CPython pytest. Real-board validation is an extra layer for behavior that mocks and unix-port checks cannot prove.

## What gets configured

`python scripts/run.py setup` creates two gitignored files when they do not already exist:

- `devices.yml` — your local board registry and default target selection
- `device-config.yml` — shared environment values for tests (WiFi, MQTT, NTP, and similar settings)

They are intentionally local-only. Fill them in for your machine and boards; do not commit them.

## 1. Generate the starter files

```bash
python scripts/run.py setup
```

If the files already exist, setup leaves them alone.

## 2. Configure `devices.yml`

`devices.yml` has two parts:

- a top-level `defaults:` block
- a `devices:` list with one entry per board

### `defaults:`

`defaults:` controls what happens when you run `python scripts/run.py test-device` with no board-selection flags, and what the IDE play button targets for `functional_tests/`.

```yaml
defaults:
  micropython: office-esp32-mp
  circuitpython: office-esp32-cp
  deploy_mode: ram
  ide_runtime: micropython
```

Fields:

| Field | Meaning |
|---|---|
| `micropython` | Default MicroPython device ID from the `devices:` list |
| `circuitpython` | Default CircuitPython device ID from the `devices:` list |
| `deploy_mode` | Workspace-wide default deploy mode: `ram` or `flash` |
| `ide_runtime` | Which runtime(s) IDE play buttons target: `micropython`, `circuitpython`, or `both` |

Notes:

- If `micropython` or `circuitpython` is omitted, ChuMicro falls back to the first configured board of that runtime.
- `ide_runtime: both` collects each `functional_tests/test_*.py` function twice, once per runtime, so the IDE shows separate results.

### `devices:` entries

Each device entry must define:

- `id`
- `runtime` (`micropython` or `circuitpython`)
- `address`

Typical serial examples:

```yaml
devices:
  - id: office-esp32-cp
    runtime: circuitpython
    address: /dev/cu.usbmodem101
    description: Desk board running CircuitPython
    serial_baudrate: 115200
    deploy_mode: ram
    circuitpy_drive_path: /Volumes/CIRCUITPY

  - id: office-esp32-mp
    runtime: micropython
    address: /dev/cu.usbserial-0001
    description: Desk board running MicroPython
    serial_baudrate: 115200
    deploy_mode: flash
```

Supported fields today:

| Field | Required | Meaning |
|---|---|---|
| `id` | yes | Stable name used by `defaults:` and CLI overrides |
| `runtime` | yes | `micropython` or `circuitpython` |
| `address` | yes | Serial port / device address used by the transport |
| `description` | no | Free-form label for humans |
| `connection_type` | no | Currently `serial` |
| `serial_baudrate` | no | Serial baud rate; defaults to `115200` |
| `deploy_mode` | no | Per-device override for `ram` or `flash` |
| `circuitpy_drive_path` | no | CIRCUITPY mount path for CircuitPython flash mode |
| `setup_command` | no | Reserved for future per-device setup hooks; currently parsed but not used by the transport layer |

### Deploy mode behavior

| Deploy mode | MicroPython | CircuitPython |
|---|---|---|
| `ram` | `mpremote mount`-based execution | raw-REPL inline execution |
| `flash` | `mpremote fs cp -r` copy mode | copy to CIRCUITPY drive, then import from flash |

Use `ram` for day-to-day functional-test iteration. Use `flash` when a board cannot hold the RAM-mode payload comfortably or when you need persistence semantics.

## 3. Configure `device-config.yml`

`device-config.yml` is a plain YAML mapping injected into device runs as `device_config`.

Example:

```yaml
wifi:
  ssid: "YourNetworkName"
  password: "YourNetworkPassword"

mqtt:
  broker: "192.168.1.100"
  port: 1883
```

Typical uses:

- WiFi credentials for networking tests
- broker addresses for MQTT tests
- NTP servers or other environment-specific values

If a library does not need shared environment data, the file can stay mostly empty.

## 4. Run device tests from the CLI

### Default target set

```bash
python scripts/run.py test-device
```

This uses `devices.yml` defaults:

- active runtime set from `defaults.ide_runtime`
- board selection from `defaults.micropython` / `defaults.circuitpython`
- deploy mode from each device entry, falling back to `defaults.deploy_mode`

### Common filters

```bash
# One runtime only
python scripts/run.py test-device --runtime micropython

# Both runtimes, using defaults-backed board selection
python scripts/run.py test-device --runtime both

# Override just one selected board
python scripts/run.py test-device --micropython-device office-esp32-mp
python scripts/run.py test-device --circuitpython-device office-esp32-cp

# Limit to one library
python scripts/run.py test-device --library timing

# Limit to one file by filename substring (matches filenames only)
python scripts/run.py test-device --library timing --file test_heartbeat

# Limit to one test function by function-name substring
# (matches function names only — does NOT match filenames)
python scripts/run.py test-device --library timing --test heartbeat_fires

# Both filters compose as AND — one file AND one function
python scripts/run.py test-device \
    --library timing --file test_heartbeat --test heartbeat_fires

# Force flash mode for this run
python scripts/run.py test-device --library timing --deploy-mode flash
```

## 5. Run `functional_tests/` from an IDE

The repository registers a pytest plugin that intercepts explicit `functional_tests/` targets and routes them to hardware instead of importing them on the host.

What that means in practice:

- host-side test runs still ignore `functional_tests/`
- clicking play on a `functional_tests/test_*.py` file or test function targets the configured board(s)
- if `devices.yml` does not exist yet, the test is skipped with a message telling you to run setup

### PyCharm

PyCharm is the primary live-tested IDE path during current device-testing development. Once `devices.yml` is configured, play buttons on `functional_tests/` files, directories, and functions route to hardware.

### VS Code

VS Code uses the same pytest entrypoint and committed workspace settings/tasks as PyCharm. The structural support is present:

- `.vscode/settings.json` enables pytest and points Pylance at all workspace source roots
- `.vscode/tasks.json` includes a `Test Device` task
- explicit `functional_tests/` targets go through the same pytest plugin

A dedicated live end-to-end VS Code validation pass remains on `plans/next-up.md`, so if you hit a VS Code-only issue, treat that as a real bug rather than user error.

## 6. How functional tests differ from host tests

| Test type | Location | How to run |
|---|---|---|
| Host/unit tests | `libraries/<name>/tests/` | `python scripts/run.py test --libraries <name>` |
| Real-board functional tests | `libraries/<name>/functional_tests/` | `python scripts/run.py test-device --library <name>` or an IDE play button |
| Cross-runtime unix-port tests | reuses `tests/` | `python scripts/run.py test-runtime-matrix` |

## 7. CI and environment overrides

Two environment variables are supported for file-path overrides:

- `CHUMICRO_DEVICES` — alternate path to `devices.yml`
- `CHUMICRO_DEVICE_CONFIG` — alternate path to `device-config.yml`

These are intended for CI or unusual local layouts. They do **not** replace the normal per-runtime board selection flow in `devices.yml`.

## Troubleshooting

| Symptom | Likely cause | What to do |
|---|---|---|
| `No devices.yml found` | You have not generated local config yet | Run `python scripts/run.py setup` |
| `No devices configured in devices.yml` | The file exists but `devices:` is empty or defaults do not match real entries | Add at least one board entry and update `defaults:` |
| CircuitPython RAM-mode run fails before tests start | Inline payload is too large for available heap | Re-run with `--deploy-mode flash` or set that board's `deploy_mode: flash` |
| Flash mode cannot find CIRCUITPY | Host mount path not auto-detected | Set `circuitpy_drive_path` explicitly in `devices.yml` |
| A normal `python scripts/run.py test` run ignores `functional_tests/` | Expected behavior | Use `test-device` or explicitly target the `functional_tests/` path from your IDE |

## Related guides

- [Contributing guide](../../CONTRIBUTING.md)
- [Development with PyCharm](development-pycharm.md)
- [Development with VS Code](development-vscode.md)
- [Development with Other Editors](development-other-editors.md)
- [Pull requests](pull-requests.md)
- [Decision 0027](../../plans/decisions/0027-device-testing-infrastructure.md)
- [Decision 0028](../../plans/decisions/0028-deploy-modes.md)
