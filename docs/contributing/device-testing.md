# Device Testing

<img src="https://chumicro.com/assets/chumicro-head.png" alt="" align="left" width="64" style="margin-right: 16px; margin-bottom: 8px;">

A library's `functional_tests/` run on a real MicroPython or CircuitPython board, and so can its unit suite. [CONTRIBUTING § Testing](https://github.com/ChuMicro/ChuMicro/blob/main/CONTRIBUTING.md#testing) places both among the other test layers.

<br clear="left">

The *deploy mode* decides how code reaches the board. [Deploys and file persistence](../troubleshooting/deploys-and-file-persistence.md#the-deploy-prints-switching-to-flash-mode-after-you-asked-for-ram) defines flash and RAM mode, and [Deploy mode behavior](#deploy-mode-behavior) below shows what each does on each runtime.

## Starter files

`python scripts/run.py setup` creates `devices.yml`, `workspace.yml`, and `secrets.toml` at the repository root when they are missing, and leaves existing ones alone. [Workspace, devices, and secrets](config-files.md) explains each file, and [Decision 0057](https://github.com/ChuMicro/ChuMicro/blob/main/plans/decisions/0057-two-file-config.md) records why the settings are split this way.

A new `devices.yml` starts with an empty `devices: []` list. `add-device` fills it in, and hand edits to the YAML work too.

## Register a board with `add-device`

```bash
python scripts/run.py add-device pi-pico-w-mp --address /dev/cu.usbmodem1101
```

`run.py add-device` forwards to `chumicro-workspace add-device`. It probes the connected board for its UID, machine type, and `board_id`, and writes the entry to `devices.yml`. On the first registration of each runtime, it also fills in `defaults.micropython` or `defaults.circuitpython`.

Both arguments are optional. Without an id, the command derives one from the board's name. Without `--address`, it picks the only serial port it sees, or asks you to choose one.

`--runtime` skips the runtime auto-detect, which saves time, and `--description "Desk board"` adds a free-form note. `python scripts/run.py add-device --help` lists every flag.

### Re-probing, replacing, and deleting entries

- `chumicro-workspace add-device <id> --force` **updates** an entry. It re-probes the board and refreshes its address and hardware fields, and keeps the `description` and `deploy_mode` you typed. Use it when a board moves ports.
- `chumicro-workspace reset-device <id> --yes` **replaces** an entry. It re-probes the connected board and rebuilds the entry from what the board reports, dropping hand edits to `description`, `deploy_mode`, and `serial_baudrate`. The id and its `defaults.<runtime>` binding survive. Use it when an entry has drifted, or the board now runs the other runtime. The board must be connected, and a failed probe points you to `remove-device` or `add-device`.
- `chumicro-workspace remove-device <id> --yes` **deletes** an entry, and clears any `defaults:` pointer to it so the file stays loadable. No board needs to be connected.

`reset-device` and `remove-device` require `--yes` because they discard user-owned fields a probe cannot regenerate.

## Tune `devices.yml`

`add-device` writes a complete entry, so hand edits are optional. They set a per-device deploy mode, change `defaults.ide_runtime`, or adjust the defaults.

<details>
<summary>defaults: block, fields and behavior (click to expand)</summary>

`defaults:` picks the boards `python scripts/run.py test-libraries-functional` uses when run with no board-selection flags, and the boards an IDE play button targets for `functional_tests/`.

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
| `deploy_mode` | Workspace-wide default deploy mode: `flash`, the default per [Decision 0047](https://github.com/ChuMicro/ChuMicro/blob/main/plans/decisions/0047-deploy-mode-flash-default.md), or `ram` |
| `ide_runtime` | Which runtime IDE play buttons target: `micropython`, `circuitpython`, or `both` |

Notes:

- With `micropython` or `circuitpython` left out, ChuMicro falls back to the first configured board of that runtime.
- `ide_runtime: both` collects each `functional_tests/test_*.py` function twice, once per runtime, so the IDE shows separate results.

</details>

<details>
<summary>devices: entries, fields and per-device overrides (click to expand)</summary>

Typical serial entries:

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

Fields:

| Field | Required | Meaning |
|---|---|---|
| `id` | yes | Stable name used by `defaults:` and CLI overrides |
| `runtime` | yes | `micropython` or `circuitpython` |
| `address` | yes | Serial port the transport opens |
| `description` | no | Free-form label for humans |
| `hardware` | no | Board identity (`uid`, `machine`, `board_id`) that `add-device` writes from the probe |
| `connection_type` | no | `serial`, the only transport |
| `serial_baudrate` | no | Serial speed, default `115200` |
| `deploy_mode` | no | Per-device *preference*: `ram` or `flash` |
| `supports_ram_mode` | no | Board *capability*, default `true`. Set `false` only for a board that cannot run RAM mode at all, and a requested `ram` deploy then switches to `flash` with a message. A board where RAM is merely tight, such as the Pi Pico W, stays `true`: each library's `requires_flash` handles tightness |

</details>

### Deploy mode behavior

| Deploy mode | MicroPython | CircuitPython |
|---|---|---|
| `ram` | `mpremote mount`-based execution | raw-REPL inline execution |
| `flash` | `mpremote fs cp -r` copy mode | copy to CIRCUITPY drive, then import from flash |

`flash` is the default for project deploys, examples, and functional tests ([Decision 0047](https://github.com/ChuMicro/ChuMicro/blob/main/plans/decisions/0047-deploy-mode-flash-default.md)), because it runs your code the way a shipped deploy does. Opt into `ram` per device or per run while iterating on a single library that needs no persistence and no other libraries, to keep the edits off the board's flash.

#### When `flash` is required

`ram` suits a single-library functional test: no ChuMicro dependencies beyond the library under test, and no runtime-config file.

A test needs `flash` when it exercises:

- runtime-config-driven setup
- `kvstore` persistence across resets
- full `deploy → wifi → mqtt` chains
- `extra_files` staging on CircuitPython, which CircuitPython RAM-mode deploys lack ([Decision 0056](https://github.com/ChuMicro/ChuMicro/blob/main/plans/decisions/0056-transport-extra-files-staging.md))

When a multi-library test fails under `ram`, switch the device's `deploy_mode` to `flash`. CircuitPython RAM mode has no `/remote/` staging path to fall back on.

A requested `ram` deploy switches to `flash` by itself, and prints why, when the staged set holds a non-`.py` data file, when any library in the dependency closure declares `requires_flash`, or when the device sets `supports_ram_mode: false`. Set `deploy_mode: flash` by hand for a board known to be too small for the RAM payload.

## On-device unit sweep (`test-unit-on-device`)

The on-device unit sweep runs each library's unit suite, `libraries/<name>/tests/`, on a real board. It catches behavior that differs between a unix port and the same runtime on a real chip.

```bash
python scripts/run.py test-unit-on-device                 # both runtimes, all libraries
python scripts/run.py test-unit-on-device --library timing # one library
python scripts/run.py test-unit-on-device --runtime micropython
```

Preflight runs the sweep only with `--with-device-unit`, after the `--with-functional` tail. A runtime with no configured board is skipped.

**Each library picks its own mode, preferring RAM.** The sweep prefers `ram`, where the functional tests default to `flash`, because it exists to prove RAM-capable libraries on real chips. A library that declares `requires_flash`, or ships a non-`.py` data file of its own, runs in `flash`, and the rest of the sweep stays in `ram`. A dependency's data file leaves a library in RAM: `chumicro_ntp` depends on `chumicro_sockets`, which ships `_ca_bundle.der`, and still runs in the RAM group, because its unit tests never reach the bundle.

**Libraries run in one session per mode.** The sweep groups libraries by mode and runs each group as one session per runtime, the flash group first. A run on a RAM-capable board becomes a fast RAM session over the light libraries and a flash session over the rest, with no transport switch between libraries.

**The sweep checks behavior only.** `coverage.py` cannot trace MicroPython or CircuitPython bytecode, so the sweep takes no `--coverage-threshold`. The coverage gate belongs to the CPython and unix-port runs. A failing test on the board fails the sweep, and `preflight --with-device-unit` with it.

### Large test modules on a 256 KB board

Every cross-runtime test file runs green on a freshly reset Pi Pico W under both CircuitPython and MicroPython ([Decision 0072](https://github.com/ChuMicro/ChuMicro/blob/main/plans/decisions/0072-large-test-modules-on-constrained-boards.md)). The Pi Pico W, with 264 KB of RAM, is the board class these libraries exist for. A board with PSRAM, such as the Lolin S2, hides the failures this rule catches.

The sweep runs each test file through one interpreter on the board. A large module holds the library it imports and all of its test classes in memory at once, and on a Pi Pico W that can raise `MemoryError` even on a freshly reset board running that file alone.

- `--per-file`, on `scripts/run.py test-unit-on-device` or on any flash-mode `pytest` run, soft-resets the interpreter before each test file instead of each library, so a file never inherits a sibling's memory. Each reset adds a reboot, so the default per-library reset stays the fast path for PSRAM boards and small libraries.
- A file that still raises `MemoryError` alone on a fresh Pi Pico W gets split until each part fits. The split mirrors the source modules where one exists, and otherwise cuts the file mechanically, leaving test bodies byte-identical. The size that fits depends on the library and differs between CircuitPython and MicroPython, so each library finds its own on the bench.

## Configure `secrets.toml`

Every functional test inherits `secrets.toml`'s credentials and device-bound defaults at deploy time. Fill in your wifi credentials and your broker host once per clone, as [secrets.toml](config-files.md#secretstoml-runtime-credentials-for-on-device-code) shows. The mqtt library refuses to dial a third-party broker silently, so MQTT tests need the broker host.

With `secrets.toml` missing, or still holding the placeholder SSID, these tests skip, so a fresh clone stays green.

<details>
<summary>How the runtime-config staging works (click to expand)</summary>

Each library's `functional_tests/conftest.py` calls `chumicro_workspace.compose_runtime_config(secrets_toml=…, project_config=…)` from its `pytest_configure` hook, then hands the merged dict to `set_runtime_config(config, payload)`, imported with `from chumicro_pytest_device.runtime_config import set_runtime_config`. The pytest-device plugin msgpack-encodes the payload once per session and stages it with `transport.stage(extra_files={"/runtime_config.msgpack": …})`. When `secrets.toml` is missing or carries the placeholder SSID, the conftest registers `None` and the on-device test skips.

</details>

The networking libraries' tests, in `libraries/{wifi,requests,http_server,mqtt,sockets,websockets}`, read the wifi credentials. The MQTT tests read the broker address, and a test can read an NTP server or another environment-specific value the same way. A library that needs no shared environment data needs no `functional_tests/config.toml`.

## Run device tests from the CLI

### Default target set

```bash
python scripts/run.py test-libraries-functional
```

With no flags, the command reads the `devices.yml` defaults:

- the runtime set from `defaults.ide_runtime`
- the boards from `defaults.micropython` and `defaults.circuitpython`
- the deploy mode from each device entry, falling back to `defaults.deploy_mode`

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
python scripts/run.py test-libraries-functional --library timing --file test_rate

# Scope to functions whose name contains the substring
python scripts/run.py test-libraries-functional --library timing --function due_fires

# Force flash mode
python scripts/run.py test-libraries-functional --library timing --deploy-mode flash
```

**Scoping flags:**

- `--library <name>`: restrict to one library.
- `--file <substring>`: match test file names.
- `--function <substring>`: match test function names.
- Flags combine as AND: `--library timing --file test_rate --function rejects_zero_period` runs only `test_rate_rejects_zero_period` inside `test_rate.py` in `timing/`.
- A filter that matches nothing exits 2, so a typo fails loudly.

The tests always read `devices.yml` from the workspace root, so a CI job places one there before running them.

## Run functional tests through pytest

`scripts/run.py test-libraries-functional` wraps pytest: it runs `pytest libraries/<name>/functional_tests/` with the device plugin's flags. Calling pytest directly targets a folder or a whole file:

```bash
# Whole directory
pytest libraries/timing/functional_tests/

# One file
pytest libraries/timing/functional_tests/test_rate.py
```

The target boards still follow the `devices.yml` defaults. Without a populated `devices.yml`, the tests skip with a message.

The [`chumicro-pytest-device` README](https://github.com/ChuMicro/ChuMicro/tree/main/workbench/pytest-device/README.md#pytest-options) lists every option the plugin adds to pytest, among them `--target`, `--runtime`, `--deploy-mode`, `--per-file`, and `--pr-summary`.

## Run unix-port unit tests from an IDE

`pytest libraries/<name>/tests/` runs CPython. Adding `--target unix-port --runtime <X>` runs the same files in a MicroPython or CircuitPython unix-port subprocess.

```bash
# Whole library's tests under MicroPython unix-port.
pytest libraries/timing/tests --target unix-port --runtime micropython

# One file under both unix-port runtimes (parametrized once per runtime).
pytest libraries/timing/tests/test_deadline.py --target unix-port --runtime both

# One function under CircuitPython unix-port.
pytest libraries/timing/tests/test_deadline.py::test_rate_fires_across_tick_wraparound --target unix-port --runtime circuitpython
```

An IDE play button on a `tests/` file runs CPython pytest. For the unix-port path, add a run configuration that passes `--target unix-port --runtime <X>` and `--no-cov`, since coverage isn't collected through a subprocess.

## Run workbench functional tests

Workbench packages, the laptop-only tools under `workbench/<name>/` ([Decision 0032](https://github.com/ChuMicro/ChuMicro/blob/main/plans/decisions/0032-workbench-host-tools.md)), can ship their own `functional_tests/`. These tests run on your laptop: the tool *drives* a connected board through its public API, and nothing in the test ships onto the board.

```bash
# Run every workbench's functional_tests/ suite.
python scripts/run.py test-workbench-functional

# One workbench package.
python scripts/run.py test-workbench-functional --workbench deploy

# Scope by file / function like test-libraries-functional.
python scripts/run.py test-workbench-functional --file test_deploy_files_hardware --function circuitpython_ram -v
```

Each suite's own `conftest.py` picks its board, usually from the `devices.yml` defaults, so `test-workbench-functional` takes no runtime or device flags. Change the target board through those defaults, or through the suite's fixtures. A suite skips when `devices.yml` is missing or names no matching board.

## Run `functional_tests/` from an IDE

The repository's pytest plugin sends an explicit `functional_tests/` target to the board instead of importing it on the laptop:

- A plain laptop test run skips `functional_tests/`.
- A play button on a `functional_tests/test_*.py` file, directory, or function targets the configured boards.
- Without a `devices.yml`, the test skips with a message naming the command that registers a board.

The test tree shows extra `Setup: <runtime>` and `Run overhead: <runtime>` nodes beside the test functions. PyCharm and VS Code both run these targets through the plugin: see [Development with PyCharm](development-pycharm.md) and [Development with VS Code](development-vscode.md).

## Wiping a board's filesystem

A full board fails mid-test with `mpremote: cp: ...: No space left on device`. Flash-mode test runs copy files onto the board and leave old ones behind, so the filesystem slowly fills. A Pi Pico W on MicroPython, with about 850 KB of filesystem, fills first. A board with 2 MB lasts longer and still fills eventually.

```bash
# Erase everything, then deploy an example onto the clean board.
chumicro-workspace deploy-example timing rate_blink --device <id> --wipe

# Erase everything and leave the board empty.
# Without --yes the command exits 2 and touches nothing.
chumicro-workspace reset-board --device <id> --yes
```

`chumicro-workspace deploy <project> --wipe` erases the same way, through the same code, in a workspace with a `projects/` folder. Each runtime erases its filesystem this way:

| Runtime / board family | Recipe |
|---|---|
| **CircuitPython** (any board) | `import storage; storage.erase_filesystem()`: reformats FAT, hard-resets the board, host re-enumerates USB-CDC |
| **MicroPython on rp2** (Pi Pico W) | `os.umount('/'); os.VfsLfs2.mkfs(rp2.Flash()); machine.soft_reset()` |
| **MicroPython on esp32** (Lolin S2 family) | `os.umount('/'); os.VfsLfs2.mkfs(esp32.Partition.find(TYPE_DATA, label='vfs')[0]); machine.soft_reset()` |
| Other MicroPython boards | `RuntimeError` until a verified recipe lands |

The MicroPython path reformats with `mkfs` instead of deleting files one by one. LittleFS keeps metadata and wear-leveling blocks that survive a file-by-file delete, so a small board can still run out of space after that kind of wipe. `mkfs` recovers every block. The recipe is verified on a Pi Pico W and a Lolin S2 under MicroPython.

The wipe erases every file the runtime can see: `/lib`, `code.py` / `main.py`, `runtime_config.msgpack`, and also `settings.toml`, a hand-edited `boot.py`, and anything else you uploaded. The firmware stays untouched.

A RAM-mode board has nothing to wipe, so the command prints a note and does nothing.

## Troubleshooting

| Symptom | Likely cause | What to do |
|---|---|---|
| `No devices.yml found` | The starter files are missing, or no board is registered | Register a board with `python scripts/run.py add-device <id> --address <port>` |
| `No devices registered in devices.yml` | The `devices:` list is empty, or `defaults:` names no real entry | Register a board with `add-device`, and check `defaults:` |
| CircuitPython RAM-mode run fails before tests start | The inline payload is too large for the free heap | Re-run with `--deploy-mode flash`, or set that board's `deploy_mode: flash` |
| Flash mode cannot find CIRCUITPY | The host shows no `CIRCUITPY*` mount | Replug the board's USB cable and confirm Finder or `mount` shows the drive. See [CIRCUITPY on macOS](../troubleshooting/macos-circuitpy.md) |
| A normal `python scripts/run.py test` run ignores `functional_tests/` | Expected behavior | Use `test-libraries-functional`, or target the `functional_tests/` path from your IDE |
| `mpremote: cp: ...: No space left on device` mid-deploy | Files left by earlier runs fill the LittleFS partition | `chumicro-workspace reset-board --device <id> --yes`, as [Wiping a board's filesystem](#wiping-a-boards-filesystem) describes |
| Lolin S2 CircuitPython deploys take 30 to 60 s per example | The board writes flash slowly | Wait it out, or iterate on a faster board such as a Pi Pico W. See [Known board quirks](../troubleshooting/board-quirks.md) |
| CIRCUITPY visible, and every write fails with `Read-only file system` | The board's filesystem went read-only, or macOS mounted it read-only | Unplug and replug, or run `chumicro-workspace reset-board --device <id> --yes`. See [CIRCUITPY on macOS](../troubleshooting/macos-circuitpy.md) |

## Related guides

- [Contributing guide](https://github.com/ChuMicro/ChuMicro/blob/main/CONTRIBUTING.md)
- [Development with PyCharm](development-pycharm.md)
- [Development with VS Code](development-vscode.md)
- [Development with Other Editors](development-other-editors.md)
- [Pull requests](pull-requests.md)
- [Decision 0027](https://github.com/ChuMicro/ChuMicro/blob/main/plans/decisions/0027-device-testing-infrastructure.md)
- [Decision 0028](https://github.com/ChuMicro/ChuMicro/blob/main/plans/decisions/0028-deploy-modes.md)
