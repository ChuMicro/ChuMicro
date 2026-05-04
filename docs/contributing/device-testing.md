# Device Testing

This guide covers the real-board testing workflow for ChuMicro libraries.

Use it when you want to:

- run `functional_tests/` on a connected MicroPython or CircuitPython board
- understand how `devices.yml`, `workspace.yml`, and `secrets.yml` are structured
- use `python scripts/run.py test-libraries-functional`
- use IDE play buttons for `functional_tests/`

Host-side `tests/` still run through normal CPython pytest. Real-board validation is an extra layer for behavior that mocks and unix-port checks cannot prove.

## What gets configured

`python scripts/run.py setup` creates two gitignored files when they do not already exist:

- `devices.yml` — your local board registry and default target selection
- `workspace.yml` — workspace-wide defaults (committed) for wifi / mqtt / quality knobs.  Per-library `functional_tests/config.toml` overrides land on top.
- `secrets.yml` — gitignored credential store referenced from `workspace.yml` via `!secret <name>` markers
- `chumicro-dev-config.toml` — *legacy* dev config still consumed by today's `libraries/*/functional_tests/conftest.py`.  Phase 4 of the unification workstream retires this file in favour of `workspace.yml` + `secrets.yml`

They are intentionally local-only. Fill them in for your machine and boards; do not commit them.

## 1. Generate the starter files

```bash
python scripts/run.py setup
```

If the files already exist, setup leaves them alone.

The starter `devices.yml` ships with an empty `devices: []` registry — same shape as the workspace-template repo's `_workspace_template/devices.yml`.  Use the `add-device` flow (next section) to populate it; hand-editing the YAML is still supported but no longer the primary path.

## 2. Register your boards via `add-device`

```bash
python scripts/run.py add-device pi-pico-w-mp --address /dev/cu.usbmodem1101
```

This is a thin shim around `chumicro-workspace add-device`.  It probes the connected board (UID, machine type, board_id), writes the entry to `devices.yml` with three-zone awareness (USER-OWNED / HARDWARE-ONCE / PROBED-ALWAYS), and fills in `defaults.{micropython,circuitpython}` on first registration of each runtime.

Pass `--runtime` if you want to skip the auto-detect probe (faster), or `--description "Desk board"` to add a free-form note.  See `python scripts/run.py add-device --help` for the full flag set.

## 3. Configure `devices.yml`

The `add-device` flow handles the common case.  Hand-editing is still useful for tuning defaults or reading what `add-device` wrote.

`devices.yml` has two parts:

- a top-level `defaults:` block
- a `devices:` list with one entry per board

### `defaults:`

`defaults:` controls what happens when you run `python scripts/run.py test-libraries-functional` with no board-selection flags, and what the IDE play button targets for `functional_tests/`.

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

## 3. Configure `workspace.yml` + `secrets.yml`

Workspace-wide defaults that every functional test inherits at deploy time.  `workspace.yml` is committed (no secrets), `secrets.yml` is gitignored (real credentials).  Materialised by `setup`; the workbench package `chumicro-workspace` owns the canonical content (same source-of-truth that ships to the workspace-template repo).

Edit `secrets.yml` once per clone — uncomment and fill in:

```yaml
wifi_password: my-real-wifi-password
api_token: 1234abcd
```

`workspace.yml` references those names via `!secret <name>` (already wired by the materialised starter):

```yaml
defaults:
  wifi:
    ssid: replace-with-your-ap-ssid
    password: "!secret wifi_password"
  mqtt:
    broker:
      host: test.mosquitto.org
      port: 1883
```

The `!secret` marker is resolved at deploy time after merge — the on-device runtime never sees the literal `"!secret ..."` string.  Per-library overrides land in `libraries/<name>/functional_tests/config.toml` (Phase 4 wires those).

Typical uses:

- WiFi credentials for networking tests (`libraries/{wifi,requests,http_server,mqtt,sockets,websockets}`)
- broker addresses for MQTT tests
- NTP servers or other environment-specific values

If a library does not need shared environment data, no override file is needed.

### Legacy: `chumicro-dev-config.toml`

Today's `libraries/*/functional_tests/conftest.py` still reads `chumicro-dev-config.toml` directly.  Phase 4 of the unification workstream migrates each conftest to read the merged `runtime_config.msgpack` produced by the `workspace.yml` + `secrets.yml` pipeline above.  Until then, both files coexist: `setup` materialises both, and you can fill in either (or both) depending on which library's tests you're running.

## 4. Run device tests from the CLI

### Default target set

```bash
python scripts/run.py test-libraries-functional
```

This uses `devices.yml` defaults:

- active runtime set from `defaults.ide_runtime`
- board selection from `defaults.micropython` / `defaults.circuitpython`
- deploy mode from each device entry, falling back to `defaults.deploy_mode`

### Common filters

```bash
# One runtime only
python scripts/run.py test-libraries-functional --runtime micropython

# Both runtimes, using defaults-backed board selection
python scripts/run.py test-libraries-functional --runtime both

# Override just one selected board
python scripts/run.py test-libraries-functional --micropython-device office-esp32-mp
python scripts/run.py test-libraries-functional --circuitpython-device office-esp32-cp

# Scope to a library
python scripts/run.py test-libraries-functional --library timing

# Scope to files whose name contains the substring
python scripts/run.py test-libraries-functional --library timing --file test_heartbeat

# Scope to functions whose name contains the substring
python scripts/run.py test-libraries-functional --library timing --function heartbeat_fires

# Force flash mode
python scripts/run.py test-libraries-functional --library timing --deploy-mode flash
```

**Scoping flags:**

- `--library <name>` — restrict to one library.
- `--file <substring>` — match test file names (not function names).
- `--function <substring>` — match test function names (not file names).
- Flags compose as AND: `--library timing --file test_heartbeat --function fires_on_interval` runs only `fires_on_interval` inside `test_heartbeat.py` in `timing/`.
- Any filter that matches nothing exits 2 so typos don't silently pass.

## 5. Run functional tests via pytest directly

`scripts/run.py test-libraries-functional` is a thin wrapper over pytest — it runs `pytest libraries/<name>/functional_tests/` with the `--chumicro-*` flags the device plugin exposes.  Invoking pytest directly is useful when you want pytest-native UX (a specific folder, file, or method) without going through `scripts/run.py`.

```bash
# Whole directory
pytest libraries/timing/functional_tests/

# One file
pytest libraries/timing/functional_tests/test_heartbeat.py

# One function
pytest libraries/timing/functional_tests/test_heartbeat.py::test_heartbeat_fires

# Keyword filter (pytest-native)
pytest libraries/timing/functional_tests/ -k heartbeat
```

Target device selection still follows `devices.yml` defaults. Without a populated `devices.yml`, the tests skip with a clear message rather than failing.

### `--chumicro-*` plugin options

Driving pytest directly gives you access to the same overrides `test-libraries-functional` passes through the plugin:

| Flag | Purpose |
|---|---|
| `--chumicro-runtime {micropython,circuitpython,both}` | Override `defaults.ide_runtime` from `devices.yml`. |
| `--chumicro-micropython-device <id>` | Override `defaults.micropython` for this run. |
| `--chumicro-circuitpython-device <id>` | Override `defaults.circuitpython` for this run. |
| `--chumicro-deploy-mode {ram,flash}` | Override each device's `deploy_mode`. |
| `--chumicro-pr-summary` | Print the Markdown PR block at session end (paste-ready).  Opt-in so IDE play-button runs stay quiet. |
| `--chumicro-pr-summary-command <str>` | Literal command string rendered inside the PR block's `- Command:` line.  `test-libraries-functional` passes its reconstructed CLI invocation here; direct pytest runs can supply their own label or omit it and get a bare `pytest`. |

## 6. Run workbench functional tests — `test-workbench-functional`

Workbench packages (`workbench/<name>/`, Decision 0032) can ship their own `functional_tests/` directories.  Unlike library functional tests, these run host-side — the workbench tool is the project *driving* a connected board through its public API rather than code that ships onto the device.

```bash
# Run every workbench's functional_tests/ suite.
python scripts/run.py test-workbench-functional

# One workbench package.
python scripts/run.py test-workbench-functional --workbench deploy

# Scope by file / function like test-libraries-functional.
python scripts/run.py test-workbench-functional --file test_deploy_files_hardware --function circuitpython_ram -v
```

Device selection lives inside each suite's own `conftest.py` (typically by reading `devices.yml` defaults), so `test-workbench-functional` itself exposes no runtime / device flags — change the target board via `devices.yml` defaults or by editing the suite's fixtures.  Suites skip cleanly when `devices.yml` is missing or no matching board is configured.

## 7. Run `functional_tests/` from an IDE

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
- `.vscode/tasks.json` includes a `Test Libraries Functional` task
- explicit `functional_tests/` targets go through the same pytest plugin

A dedicated live end-to-end VS Code validation pass remains on `plans/next-up.md`, so if you hit a VS Code-only issue, treat that as a real bug rather than user error.

## 8. How functional tests differ from host tests

| Test type | Location | How to run |
|---|---|---|
| Host/unit tests | `libraries/<name>/tests/` | `python scripts/run.py test --libraries <name>` |
| Real-board functional tests | `libraries/<name>/functional_tests/` | `python scripts/run.py test-libraries-functional --library <name>` or an IDE play button |
| Workbench hardware-gated tests | `workbench/<name>/functional_tests/` | `python scripts/run.py test-workbench-functional --workbench <name>` |
| Cross-runtime unix-port tests | reuses `tests/` | `python scripts/run.py test-all-runtimes` |

## 9. Alternate `devices.yml` locations

`devices.yml` is always resolved at `<workspace_root>/devices.yml`. CI or
unusual local layouts can drop a `devices.yml` at the workspace root
before running tests; nothing else is needed.

## Troubleshooting

| Symptom | Likely cause | What to do |
|---|---|---|
| `No devices.yml found` | You have not generated local config yet | Run `python scripts/run.py setup` |
| `No devices configured in devices.yml` | The file exists but `devices:` is empty or defaults do not match real entries | Add at least one board entry and update `defaults:` |
| CircuitPython RAM-mode run fails before tests start | Inline payload is too large for available heap | Re-run with `--deploy-mode flash` or set that board's `deploy_mode: flash` |
| Flash mode cannot find CIRCUITPY | Host mount path not auto-detected | Set `circuitpy_drive_path` explicitly in `devices.yml` |
| A normal `python scripts/run.py test` run ignores `functional_tests/` | Expected behavior | Use `test-libraries-functional` or explicitly target the `functional_tests/` path from your IDE |

## Related guides

- [Contributing guide](../../CONTRIBUTING.md)
- [Development with PyCharm](development-pycharm.md)
- [Development with VS Code](development-vscode.md)
- [Development with Other Editors](development-other-editors.md)
- [Pull requests](pull-requests.md)
- [Decision 0027](../../plans/decisions/0027-device-testing-infrastructure.md)
- [Decision 0028](../../plans/decisions/0028-deploy-modes.md)
