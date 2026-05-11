# Device Testing

This guide covers the real-board testing workflow for ChuMicro libraries.

Use it when you want to:

- run `functional_tests/` on a connected MicroPython or CircuitPython board
- understand how `devices.yml` and `workspace.yml` are structured
- use `python scripts/run.py test-libraries-functional`
- use IDE play buttons for `functional_tests/`

Host-side `tests/` still run through normal CPython pytest. Real-board validation is an extra layer for behavior that mocks and unix-port checks cannot prove.

## What gets configured

`python scripts/run.py setup` creates three gitignored files at the repo root when they do not already exist:

- `devices.yml` — your local board registry and default target selection
- `workspace.yml` — host-side machinery (library_sources, deploy_targets, quality knobs); not a credentials file
- `secrets.toml` — workspace-wide credentials + device-bound defaults (wifi SSID/password, broker host/port/auth) that flow into `runtime_config.msgpack` at deploy time.  Per-library `functional_tests/config.toml` overrides land on top via deep-merge.

Full per-file detail (shape, purpose, who edits what) lives in [config-files.md](config-files.md).  The split lands per [Decision 0057](../../plans/decisions/0057-two-file-config.md).

## 1. Generate the starter files

```bash
python scripts/run.py setup
```

If the files already exist, setup leaves them alone.

The first-materialised `devices.yml` ships with an empty `devices: []` registry — the same canonical shape both the mono-repo and the workspace-template repo materialise from `chumicro_deploy.read_devices_yml_template` (schema and template co-located).  Use the `add-device` flow (next section) to populate it; hand-editing the YAML is still supported but no longer the primary path.

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
| `setup_command` | no | Reserved for future per-device setup hooks; currently parsed but not used by the transport layer |

### Deploy mode behavior

| Deploy mode | MicroPython | CircuitPython |
|---|---|---|
| `ram` | `mpremote mount`-based execution | raw-REPL inline execution |
| `flash` | `mpremote fs cp -r` copy mode | copy to CIRCUITPY drive, then import from flash |

Use `ram` for day-to-day functional-test iteration. Use `flash` when a board cannot hold the RAM-mode payload comfortably or when you need persistence semantics.

#### When `flash` is required, not optional

`ram` is fine for single-library unit-style functional tests (no chumicro deps beyond the library under test, no runtime-config file). `flash` is **required** when a test exercises a multi-stack chain — runtime-config-driven setup, `kvstore` persistence semantics across resets, full `deploy → wifi → mqtt` chains, or any test that needs `extra_files` staging on CircuitPython (CP RAM-mode deploy doesn't support `extra_files`, see [Decision 0056](../../plans/decisions/0056-transport-extra-files-staging.md)). If a multi-stack test fails under `ram`, switch the device's `deploy_mode` to `flash` rather than chasing fallback paths like staging files via `/remote/` — they don't exist on CP RAM mode for a reason.

## 3. Configure `secrets.toml`

Credentials and device-bound defaults that every functional test inherits at deploy time, in one gitignored file.  Materialised by `setup` from the canonical template (`chumicro_workspace.read_secrets_toml_template`), carrying placeholders for `wifi.ssid` and `mqtt.broker.host`.

Edit `secrets.toml` once per clone — fill in your wifi credentials + your broker host (the mqtt library refuses to silently dial a third-party broker, so this is required for mqtt-touching tests):

```toml
[wifi]
ssid = "my-actual-network"
password = "my-real-wifi-password"

[mqtt.broker]
host = "10.0.0.5"  # a broker you control — a LAN Mosquitto, a private cloud broker, etc.
port = 1883
# [mqtt.broker.auth]
# username = "my-user"
# password = "my-mqtt-password"
```

The deploy-time deep-merge layers `secrets.toml` → per-library `functional_tests/config.toml`.  Both layers share the same section-namespaced shape; per-library configs win at any nesting depth.  The result is flattened to dotted keys (`wifi.ssid`, `mqtt.broker.host`) and msgpack-encoded into `/runtime_config.msgpack`, which on-device tests read via `chumicro_config.load_runtime_config()` — the same API user code uses.

How the staging happens: each library's `functional_tests/conftest.py` calls `chumicro_workspace.compose_runtime_config(secrets_toml=…, project_config=…)` from its `pytest_configure` hook, then hands the merged dict to `chumicro_pytest_device.set_runtime_config(config, payload)`.  The pytest-device plugin msgpack-encodes the payload once per session and stages it via `transport.stage(extra_files={"/runtime_config.msgpack": …})`.  When `secrets.toml` is missing or carries the placeholder SSID, the conftest registers `None` and the on-device test hits its silent-skip path (no creds, no run) — fresh-clone-friendly by default.

Typical uses:

- WiFi credentials for networking tests (`libraries/{wifi,requests,http_server,mqtt,sockets,websockets}`)
- broker addresses for MQTT tests
- NTP servers or other environment-specific values

If a library does not need shared environment data, no override file is needed.


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

## Wiping a board's filesystem

Functional-test runs accumulate stage residue on the device filesystem
— `mpremote fs cp -r` (and `circup install`) are append-only, nothing
pre-cleans.  Pi Pico W MP boards in particular fill up over time
because the LittleFS partition is only ~850 KB; lolin-s2-mp is
better-off at 2 MB but still eventually hits the wall.  When this
happens, deploys fail with cryptic `mpremote: cp: ...: No space left
on device` errors mid-test.

Two ways to wipe a board:

```bash
# Wipe + redeploy in one step (the original "wipe" surface).
chumicro-workspace deploy --wipe <project> [--device <id>]

# Wipe only — leave the board idle, no follow-up deploy.
# --yes is required; no flag = exit 2 + safety message.
chumicro-workspace reset-board --device <id> --yes
```

Both routes call the same primitive
(`chumicro_deploy.TransportProtocol.wipe_filesystem`).  Per-runtime
recipe matrix:

| Runtime / board family | Recipe |
|---|---|
| **CircuitPython** (any board) | `import storage; storage.erase_filesystem()` — reformats FAT, hard-resets the board, host re-enumerates USB-CDC |
| **MicroPython on rp2** (Pi Pico W) | `os.umount('/'); os.VfsLfs2.mkfs(rp2.Flash()); machine.soft_reset()` |
| **MicroPython on esp32** (Lolin S2 family) | `os.umount('/'); os.VfsLfs2.mkfs(esp32.Partition.find(TYPE_DATA, label='vfs')[0]); machine.soft_reset()` |
| Other MicroPython substrates | `RuntimeError` until a verified recipe lands |

The MicroPython path uses `mkfs` rather than a recursive `os.remove`
walk: LittleFS metadata + wear-leveling artifacts survive a
file-by-file delete, so a board with a small partition can still
hit `ENOSPC` mid-deploy after a non-mkfs "wipe."  `mkfs` recovers
the full block budget every time.  Verified on hardware
(pi-pico-w-mp, lolin-s2-mp).

Destructive on every runtime — wipes both managed scope (`/lib/*`,
`/code.py` / `/main.py`, `runtime_config.msgpack`) **and** out-of-scope
files (`settings.toml`, hand-edited `boot.py`, uploaded assets).
Firmware partitions are untouched.

RAM / mount mode is a no-op (printed) — those modes never wrote to
flash so there's nothing persistent to wipe.

## Troubleshooting

| Symptom | Likely cause | What to do |
|---|---|---|
| `No devices.yml found` | You have not generated local config yet | Run `python scripts/run.py setup` |
| `No devices configured in devices.yml` | The file exists but `devices:` is empty or defaults do not match real entries | Add at least one board entry and update `defaults:` |
| CircuitPython RAM-mode run fails before tests start | Inline payload is too large for available heap | Re-run with `--deploy-mode flash` or set that board's `deploy_mode: flash` |
| Flash mode cannot find CIRCUITPY | Host has no `CIRCUITPY*` mount visible | Replug the board's USB cable and confirm Finder / `mount` shows the drive; see [docs/troubleshooting/macos-circuitpy.md](../troubleshooting/macos-circuitpy.md) |
| A normal `python scripts/run.py test` run ignores `functional_tests/` | Expected behavior | Use `test-libraries-functional` or explicitly target the `functional_tests/` path from your IDE |
| `mpremote: cp: ...: No space left on device` mid-deploy | LittleFS partition full of stage residue from prior runs | `chumicro-workspace reset-board --device <id> --yes` — see "Wiping a board's filesystem" above |

## Related guides

- [Contributing guide](../../CONTRIBUTING.md)
- [Development with PyCharm](development-pycharm.md)
- [Development with VS Code](development-vscode.md)
- [Development with Other Editors](development-other-editors.md)
- [Pull requests](pull-requests.md)
- [Decision 0027](../../plans/decisions/0027-device-testing-infrastructure.md)
- [Decision 0028](../../plans/decisions/0028-deploy-modes.md)
