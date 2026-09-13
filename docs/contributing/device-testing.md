# Device Testing

<img src="https://chumicro.com/assets/chumicro-head.png" alt="" align="left" width="64" style="margin-right: 16px; margin-bottom: 8px;">

This guide covers the real-board testing workflow for ChuMicro libraries.

<br clear="left">

Use it when you want to:

- run `functional_tests/` on a connected MicroPython or CircuitPython board
- understand how `devices.yml` and `workspace.yml` are structured
- use IDE play buttons for `functional_tests/`

Host-side `tests/` still run through normal CPython pytest. Real-board validation is an extra layer for behavior that mocks and unix-port checks cannot prove.

The bench holds one board at a time, and the person at the bench swaps boards and wires the panel or sensor to each. `devices.yml` reflects that: the Pi Pico W entries for both runtimes share one serial port, and `chumicro-workspace probe` tells you which board is plugged in now. A matrix cell on another board is a hand-off, so an agent driving the bench names the swap and the wiring it needs and waits, and a check that needs eyes on a panel says so before the run rather than reporting the run as unverified afterwards.

## What gets configured

`python scripts/run.py setup` creates three gitignored files at the repo root when they do not already exist:

- `devices.yml`: your local board registry and default target selection
- `workspace.yml`: host-side machinery (library_sources, deploy_targets, quality knobs); not a credentials file
- `secrets.toml`: workspace-wide credentials + device-bound defaults (wifi SSID/password, broker host/port/auth) that flow into `runtime_config.msgpack` at deploy time.  Per-library `functional_tests/config.toml` overrides land on top via deep-merge.

Full per-file detail (shape, purpose, who edits what) lives in [config-files.md](config-files.md).  The split lands per [Decision 0057](https://github.com/ChuMicro/ChuMicro/blob/main/plans/decisions/0057-two-file-config.md).

## Generate the starter files

```bash
python scripts/run.py setup
```

If the files already exist, setup leaves them alone.

The first-materialized `devices.yml` ships with an empty `devices: []` registry.  Use the `add-device` flow (next section) to populate it; hand-editing the YAML is still supported but no longer the primary path.

## Register your boards via `add-device`

```bash
python scripts/run.py add-device pi-pico-w-mp --address /dev/cu.usbmodem1101
```

This is a thin shim around `chumicro-workspace add-device`.  It probes the connected board (UID, machine type, board_id), writes the entry to `devices.yml`, and fills in `defaults.{micropython,circuitpython}` on first registration of each runtime.

Pass `--runtime` if you want to skip the auto-detect probe (faster), or `--description "Desk board"` to add a free-form note.  See `python scripts/run.py add-device --help` for the full flag set.

### Re-probing, replacing, and deleting entries

Three verbs cover an entry's later life, differing by how much they keep:

- `chumicro-workspace add-device <id> --force`: **update.** Re-probes and refreshes the address + hardware-once fields, but keeps everything you typed (description, deploy_mode). The everyday "this board moved ports / I reflashed it" path.
- `chumicro-workspace reset-device <id> --yes`: **replace.** Re-probes the connected board and rebuilds the entry from silicon, dropping accumulated hand edits (description, deploy_mode, serial_baudrate) and re-deriving the hardware identity. The id and its `defaults.<runtime>` binding survive. Use it when an entry has drifted and you want it rebuilt from truth. The board must be connected; a probe failure points you back here.
- `chumicro-workspace remove-device <id> --yes`: **delete.** Drops the entry and nulls any `defaults:` pointer to it so the file stays loadable. No board needed.

`reset-device` and `remove-device` are `--yes`-gated because they discard user-owned metadata a probe cannot regenerate.

## Tune `devices.yml` if you need to

`add-device` writes a complete, usable entry on every registration: id, runtime, address, probed hardware identity, and (on first registration of each runtime) the matching `defaults.<runtime>` pointer.  The day-to-day flow doesn't require hand-editing.

Read on if you want to override per-device deploy mode, change the `defaults.ide_runtime`, or just understand the shape of what's on disk.

<details>
<summary>defaults: block, fields and behavior (click to expand)</summary>

`defaults:` controls what happens when you run `python scripts/run.py test-libraries-functional` with no board-selection flags, and what the IDE play button targets for `functional_tests/`.

```yaml
defaults:
  micropython: office-esp32-mp
  circuitpython: office-esp32-cp
  deploy_mode: flash
  ide_runtime: micropython
```

Fields:

| Field | Meaning |
|---|---|
| `micropython` | Default MicroPython device ID from the `devices:` list |
| `circuitpython` | Default CircuitPython device ID from the `devices:` list |
| `deploy_mode` | Workspace-wide default deploy mode: `flash` (the default, per [Decision 0047](https://github.com/ChuMicro/ChuMicro/blob/main/plans/decisions/0047-deploy-mode-flash-default.md)) or `ram` |
| `ide_runtime` | Which runtime(s) IDE play buttons target: `micropython`, `circuitpython`, or `both` |

Notes:

- If `micropython` or `circuitpython` is omitted, ChuMicro falls back to the first configured board of that runtime.
- `ide_runtime: both` collects each `functional_tests/test_*.py` function twice, once per runtime, so the IDE shows separate results.

</details>

<details>
<summary>devices: entries, fields and per-device overrides (click to expand)</summary>

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
    deploy_mode: flash

  - id: office-esp32-mp
    runtime: micropython
    address: /dev/cu.usbserial-0001
    description: Desk board running MicroPython
    deploy_mode: ram      # opt out of the flash default for this board
```

Supported fields today:

| Field | Required | Meaning |
|---|---|---|
| `id` | yes | Stable name used by `defaults:` and CLI overrides |
| `runtime` | yes | `micropython` or `circuitpython` |
| `address` | yes | Serial port / device address used by the transport |
| `description` | no | Free-form label for humans |
| `connection_type` | no | Currently `serial` |
| `deploy_mode` | no | Per-device *preference* override for `ram` or `flash` |
| `supports_ram_mode` | no | Board *capability* (default `true`). Set `false` only for a board that cannot run RAM mode at all; a requested `ram` deploy then switches to `flash` with a message. Distinct from `deploy_mode`: preference is what you want, capability is what's possible. A board where RAM is merely tight (Pi Pico W's 256 KB) stays `true`: tightness is handled per-library via `requires_flash`, not by disabling the board |

</details>

### Deploy mode behavior

| Deploy mode | MicroPython | CircuitPython |
|---|---|---|
| `ram` | `mpremote mount`-based execution | raw-REPL inline execution |
| `flash` | `mpremote fs cp -r` copy mode | copy to CIRCUITPY drive, then import from flash |

`flash` is the default for project deploys, examples, and functional tests ([Decision 0047](https://github.com/ChuMicro/ChuMicro/blob/main/plans/decisions/0047-deploy-mode-flash-default.md)), because it runs your code the way a shipped deploy does.  Opt into `ram` per device or per run when you are iterating on a single library that needs no persistence and no multi-library composition, and you want the edits to stay off the board's flash.

#### When you must use `flash`

`ram` is fine for single-library unit-style functional tests: no chumicro deps beyond the library under test, no runtime-config file.

`flash` is **required** when a test exercises:

- runtime-config-driven setup
- `kvstore` persistence semantics across resets
- full `deploy → wifi → mqtt` chains
- `extra_files` staging on CircuitPython (CP RAM-mode deploy doesn't support `extra_files`, see [Decision 0056](https://github.com/ChuMicro/ChuMicro/blob/main/plans/decisions/0056-transport-extra-files-staging.md))

If a multi-stack test fails under `ram`, switch the device's `deploy_mode` to `flash` rather than chasing fallback paths like staging files via `/remote/`.  They don't exist on CP RAM mode for a reason.

You usually don't have to switch by hand for the common cases: a requested `ram` deploy automatically falls back to `flash`, with a printed explanation, when the staged set contains a non-`.py` data file, when any library in the dependency closure declares `requires_flash`, or when the device sets `supports_ram_mode: false`. The run continues in `flash`.  It is never silently mis-deployed. Hand-setting `deploy_mode: flash` is still the right move when you simply know a board can't hold the RAM payload.

## On-device unit sweep (`test-unit-on-device`)

The *functional* tests above (`libraries/<name>/functional_tests/`) exercise real I/O on a board. The **on-device unit sweep** is different: it runs each library's *cross-runtime unit suite* (`libraries/<name>/tests/`), the same suite that runs on the unix ports, on real silicon, to catch behaviour that only differs on a real MCU's MicroPython / CircuitPython.

```bash
python scripts/run.py test-unit-on-device                 # both runtimes, all libraries
python scripts/run.py test-unit-on-device --library timing # one library
python scripts/run.py test-unit-on-device --runtime micropython
```

It is **not** part of the default `preflight`. Opt in with `python scripts/run.py preflight --with-device-unit` (parallel to `--with-functional`). When no board is configured for a runtime, that runtime is skipped cleanly rather than failing.

**Per-library mode resolution, RAM-preferred.** The sweep exists to validate RAM-capable libraries on silicon, so its last-resort preference is `ram` (not the `flash` default the functional path uses). Each library is resolved through the one shared deploy-mode policy with **own-source** scoping: a library that declares `requires_flash`, or ships a non-`.py` data file, switches to `flash`, but only *that* library, not the whole sweep. A library is not poisoned by a dependency's data file: `chumicro_ntp` depends on `chumicro_sockets` (which ships `_ca_bundle.der`) yet stays in the RAM group, because its own source has no data file and a pure unit test never reaches the dependency's bundle path.

**Mode grouping.** Libraries are grouped by resolved mode and each group runs as one single-mode session per runtime (the flash group first). A `ram`-preferred run on a RAM-capable board therefore becomes a fast RAM session over the light libraries plus a flash session over the `requires_flash` / data-file ones, with no per-library transport churn.

**Behavioral pass/fail only.** `coverage.py` cannot trace MicroPython / CircuitPython bytecode, so the sweep takes no `--coverage-threshold`; the per-library coverage gate stays a unix-port / CPython concern. A per-library failure *on silicon* is the sweep's **output**, not a `preflight`-gating quality check: the run completes and reports rather than turning `preflight` red. "Output, not a gate" governs how the sweep *runs*; it does not make the finding acceptable. A `MemoryError` from a large module on the Pi Pico W is a tracked defect to fix by splitting (see below), not an accepted end-state.

### Every test file must run green on a freshly-reset Pi Pico W (CP + MP)

The on-device unit sweep runs each cross-runtime test *file* through one device interpreter. On the 264 KB Pi Pico W a very large class-organized module (the library it imports, plus that file's full set of test classes resident at once) can exhaust RAM with a `MemoryError` even on a freshly reset board running that file alone. PSRAM boards (Lolin S2) mask this; the Pico W under **both** CircuitPython and MicroPython is a distinct memory HAL, and it is the board class these libraries exist for.

**Requirement, per [Decision 0072](https://github.com/ChuMicro/ChuMicro/blob/main/plans/decisions/0072-large-test-modules-on-constrained-boards.md):** every cross-runtime test file must run green on a freshly-reset Pi Pico W on CP **and** MP. A file that OOMs there even with `--per-file` is a tracked defect, fixed by splitting, not left to run on PSRAM only.

- `scripts/run.py test-unit-on-device --per-file` (or `pytest ... --per-file`) soft-resets the interpreter before *each* test file, not just each library, so a file never inherits a sibling's resident state. This is the mechanism the requirement runs on; it adds a reboot per file, so the default per-library reset stays the fast path for PSRAM boards and small libraries.
- A file still `MemoryError`-ing alone on a fresh Pico W **must be split** until each sub-file fits, mirroring source modules where one exists, then mechanically (lossless: test bodies stay byte-identical). There is no fixed tests-per-file cap: the ceiling is library-weight-dependent and differs CP vs MP, so the target is found empirically per library on the bench: split until that library's files all run green on a freshly-reset Pico W on both runtimes.

## Configure `secrets.toml`

Credentials and device-bound defaults that every functional test inherits at deploy time, in one gitignored file.  `setup` materializes it with placeholder values for `wifi.ssid` and `mqtt.broker.host`.

Edit `secrets.toml` once per clone, filling in your wifi credentials and your broker host.  The mqtt library refuses to silently dial a third-party broker, so the broker host is required for mqtt-touching tests.  For the file's shape and the full field list, see [secrets.toml](config-files.md#secretstoml-runtime-credentials-for-on-device-code) in the config-files guide.

Per-library `functional_tests/config.toml` files override `secrets.toml` at deploy time: both layers share the same section-namespaced shape, and per-library configs win at any nesting depth.  The merged result is flattened to dotted keys (`wifi.ssid`, `mqtt.broker.host`) and msgpack-encoded into `/runtime_config.msgpack`; on-device tests read it via `chumicro_config.load_runtime_config()`, the same API user code uses.

When `secrets.toml` is missing or still carries the placeholder SSID, tests skip cleanly rather than running with empty credentials, so fresh clones stay green by default.

<details>
<summary>How the runtime-config staging works (click to expand)</summary>

Each library's `functional_tests/conftest.py` calls `chumicro_workspace.compose_runtime_config(secrets_toml=…, project_config=…)` from its `pytest_configure` hook, then hands the merged dict to `chumicro_pytest_device.set_runtime_config(config, payload)`.  The pytest-device plugin msgpack-encodes the payload once per session and stages it via `transport.stage(extra_files={"/runtime_config.msgpack": …})`.  When `secrets.toml` is missing or carries the placeholder SSID, the conftest registers `None` and the on-device test hits its silent-skip path (no creds, no run).

</details>

Typical uses:

- WiFi credentials for networking tests (`libraries/{wifi,requests,http_server,mqtt,sockets,websockets}`)
- broker addresses for MQTT tests
- NTP servers or other environment-specific values

If a library does not need shared environment data, no override file is needed.


## Run device tests from the CLI

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

- `--library <name>`: restrict to one library.
- `--file <substring>`: match test file names (not function names).
- `--function <substring>`: match test function names (not file names).
- Flags compose as AND: `--library timing --file test_heartbeat --function fires_on_interval` runs only `fires_on_interval` inside `test_heartbeat.py` in `timing/`.
- Any filter that matches nothing exits 2 so typos don't silently pass.

`devices.yml` is always resolved at `<workspace_root>/devices.yml`.  CI environments or unusual local layouts just need to drop a `devices.yml` at the workspace root before running tests.

## Run functional tests via pytest directly

`scripts/run.py test-libraries-functional` is a thin wrapper over pytest.  It runs `pytest libraries/<name>/functional_tests/` with the `--chumicro-*` flags the device plugin exposes.  Invoking pytest directly is useful when you want pytest-native UX (a specific folder, file, or method) without going through `scripts/run.py`.

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

### Plugin options

Driving pytest directly gives you access to the same overrides `test-libraries-functional` passes through the plugin:

| Flag | Purpose |
|---|---|
| `--target {device,unix-port}` | Pick the execution backend.  Default `device` (real board via `chumicro-deploy`).  `unix-port` runs each test file in a MicroPython / CircuitPython unix-port subprocess instead. |
| `--runtime {micropython,circuitpython,both}` | Under `--target device`: override `defaults.ide_runtime` from `devices.yml`.  Under `--target unix-port`: pick which runtime(s) to spawn, defaults to `both`. |
| `--micropython-device <id>` | Override `defaults.micropython` for this run (device target only). |
| `--circuitpython-device <id>` | Override `defaults.circuitpython` for this run (device target only). |
| `--micropython-binary <path>` | Unix-port MicroPython binary override (unix-port target only).  Otherwise resolved via `.tools/micropython.path` then `PATH`. |
| `--circuitpython-binary <path>` | Unix-port CircuitPython binary override (unix-port target only).  Same resolution order. |
| `--deploy-mode {ram,flash}` | Override each device's `deploy_mode` (device target only). |
| `--pr-summary` | Print the Markdown PR block at session end (paste-ready).  Opt-in so IDE play-button runs stay quiet. |
| `--pr-summary-command <str>` | Literal command string rendered inside the PR block's `- Command:` line.  `test-libraries-functional` passes its reconstructed CLI invocation here; direct pytest runs can supply their own label or omit it and get a bare `pytest`. |

## Run unix-port unit tests from an IDE

Pytest is the single front door for every runtime: bare `pytest libraries/<name>/tests/` runs CPython, and `pytest libraries/<name>/tests/ --target unix-port --runtime <X>` runs the same files under a MicroPython or CircuitPython unix-port subprocess.  The plugin owns collection in both cases and stays out of the way of plain CPython collection when `--target` is left at its `device` default.

```bash
# Whole library's tests under MicroPython unix-port.
pytest libraries/timing/tests --target unix-port --runtime micropython

# One file under both unix-port runtimes (parametrized once per runtime).
pytest libraries/timing/tests/test_heartbeat.py --target unix-port --runtime both

# One function under CircuitPython unix-port.
pytest libraries/timing/tests/test_heartbeat.py::test_heartbeat_fires_on_real_clock --target unix-port --runtime circuitpython
```

IDE play buttons that target `libraries/<name>/tests/` files go through CPython pytest by default.  To click play and get the unix-port path instead, add a dedicated run configuration that passes `--target unix-port --runtime <X>` (and `--no-cov`, since coverage isn't collected through a subprocess).  The `--target` flag is opt-in by design.  The default `pytest libraries/timing/tests/` invocation is unchanged.

## Run workbench functional tests

Workbench packages (`workbench/<name>/`, Decision 0032) can ship their own `functional_tests/` directories.  Unlike library functional tests, these run host-side.  The workbench tool is the project *driving* a connected board through its public API rather than code that ships onto the device.

```bash
# Run every workbench's functional_tests/ suite.
python scripts/run.py test-workbench-functional

# One workbench package.
python scripts/run.py test-workbench-functional --workbench deploy

# Scope by file / function like test-libraries-functional.
python scripts/run.py test-workbench-functional --file test_deploy_files_hardware --function circuitpython_ram -v
```

Device selection lives inside each suite's own `conftest.py` (typically by reading `devices.yml` defaults), so `test-workbench-functional` itself exposes no runtime / device flags.  Change the target board via `devices.yml` defaults or by editing the suite's fixtures.  Suites skip cleanly when `devices.yml` is missing or no matching board is configured.

## Run `functional_tests/` from an IDE

The repository registers a pytest plugin that intercepts explicit `functional_tests/` targets and routes them to hardware instead of importing them on the host.

What that means in practice:

- host-side test runs still ignore `functional_tests/`
- clicking play on a `functional_tests/test_*.py` file or test function targets the configured board(s)
- if `devices.yml` does not exist yet, the test is skipped with a message telling you to run setup

### PyCharm

PyCharm is the most-exercised IDE path. Once `devices.yml` is configured, play buttons on `functional_tests/` files, directories, and functions route to hardware.

### VS Code

VS Code uses the same pytest entrypoint and committed workspace settings/tasks as PyCharm. The structural support is present:

- `.vscode/settings.json` enables pytest and points Pylance at all workspace source roots
- `.vscode/tasks.json` includes a `Test Libraries Functional` task
- explicit `functional_tests/` targets go through the same pytest plugin

A dedicated live end-to-end VS Code validation pass remains on `plans/next-up.md`, so if you hit a VS Code-only issue, treat that as a real bug rather than user error.

## How functional tests differ from host tests

| Test type | Location | How to run |
|---|---|---|
| Host/unit tests | `libraries/<name>/tests/` | `pytest libraries/<name>/tests/` (iteration) or `python scripts/run.py test --libraries <name>` (with coverage gate) |
| Real-board functional tests | `libraries/<name>/functional_tests/` | `python scripts/run.py test-libraries-functional --library <name>` or an IDE play button |
| Workbench hardware-gated tests | `workbench/<name>/functional_tests/` | `python scripts/run.py test-workbench-functional --workbench <name>` |
| Cross-runtime unix-port tests | reuses `tests/` | `pytest libraries/ --target unix-port --runtime both` |

## Wiping a board's filesystem

Functional-test runs accumulate stage residue on the device filesystem.
`mpremote fs cp -r` (and `circup install`) are append-only, nothing
pre-cleans.  Pi Pico W MP boards in particular fill up over time
because the LittleFS partition is only ~850 KB; lolin-s2-mp is
better-off at 2 MB but still eventually hits the wall.  When this
happens, deploys fail with cryptic `mpremote: cp: ...: No space left
on device` errors mid-test.

Two ways to wipe a board:

```bash
# Wipe + redeploy in one step.
chumicro-workspace deploy --wipe <project> [--device <id>]

# Wipe only, leave the board idle, no follow-up deploy.
# --yes is required; no flag = exit 2 + safety message.
chumicro-workspace reset-board --device <id> --yes
```

Both routes share one implementation.  Per-runtime recipe matrix:

| Runtime / board family | Recipe |
|---|---|
| **CircuitPython** (any board) | `import storage; storage.erase_filesystem()`: reformats FAT, hard-resets the board, host re-enumerates USB-CDC |
| **MicroPython on rp2** (Pi Pico W) | `os.umount('/'); os.VfsLfs2.mkfs(rp2.Flash()); machine.soft_reset()` |
| **MicroPython on esp32** (Lolin S2 family) | `os.umount('/'); os.VfsLfs2.mkfs(esp32.Partition.find(TYPE_DATA, label='vfs')[0]); machine.soft_reset()` |
| Other MicroPython substrates | `RuntimeError` until a verified recipe lands |

The MicroPython path uses `mkfs` rather than a recursive `os.remove`
walk: LittleFS metadata + wear-leveling artifacts survive a
file-by-file delete, so a board with a small partition can still
hit `ENOSPC` mid-deploy after a non-mkfs "wipe."  `mkfs` recovers
the full block budget every time.  Verified on hardware
(pi-pico-w-mp, lolin-s2-mp).

Destructive on every runtime: wipes both managed scope (`/lib/*`,
`/code.py` / `/main.py`, `runtime_config.msgpack`) **and** out-of-scope
files (`settings.toml`, hand-edited `boot.py`, uploaded assets).
Firmware partitions are untouched.

RAM / mount mode is a no-op (printed).  Those modes never wrote to
flash so there's nothing persistent to wipe.

## Troubleshooting

| Symptom | Likely cause | What to do |
|---|---|---|
| `No devices.yml found` | You have not generated local config yet | Run `python scripts/run.py setup` |
| `No devices configured in devices.yml` | The file exists but `devices:` is empty or defaults do not match real entries | Add at least one board entry and update `defaults:` |
| CircuitPython RAM-mode run fails before tests start | Inline payload is too large for available heap | Re-run with `--deploy-mode flash` or set that board's `deploy_mode: flash` |
| Flash mode cannot find CIRCUITPY | Host has no `CIRCUITPY*` mount visible | Replug the board's USB cable and confirm Finder / `mount` shows the drive; see [docs/troubleshooting/macos-circuitpy.md](../troubleshooting/macos-circuitpy.md) |
| A normal `python scripts/run.py test` run ignores `functional_tests/` | Expected behavior | Use `test-libraries-functional` or explicitly target the `functional_tests/` path from your IDE |
| `mpremote: cp: ...: No space left on device` mid-deploy | LittleFS partition full of stage residue from prior runs | `chumicro-workspace reset-board --device <id> --yes` (see "Wiping a board's filesystem" above) |
| Lolin S2 CircuitPython deploys take 30–60 s per example | The board's flash write speed is the floor, not a recovery or retry signal | Expected; use Pi Pico W as the faster CP development target when iterating. Lolin S2 CP rsync slowness is a baseline characteristic, not a regression |
| CIRCUITPY drive visible but every write fails with `Read-only file system` | Drive is mounted RO: either the device-side FS flipped read-only, or FSKit handed the mount up with the RO flag.  Distinct from the FSKit wedge, where the drive never appears at all | `chumicro-workspace reset-board --device <id> --yes` or unplug-and-replug; see [docs/troubleshooting/macos-circuitpy.md](../troubleshooting/macos-circuitpy.md) |

## Related guides

- [Contributing guide](https://github.com/ChuMicro/ChuMicro/blob/main/CONTRIBUTING.md)
- [Development with PyCharm](development-pycharm.md)
- [Development with VS Code](development-vscode.md)
- [Development with Other Editors](development-other-editors.md)
- [Pull requests](pull-requests.md)
- [Decision 0027](https://github.com/ChuMicro/ChuMicro/blob/main/plans/decisions/0027-device-testing-infrastructure.md)
- [Decision 0028](https://github.com/ChuMicro/ChuMicro/blob/main/plans/decisions/0028-deploy-modes.md)
