# chumicro-deploy

<img src="https://raw.githubusercontent.com/ChuMicro/ChuMicro/main/support/docs/chumicro_tip.png" align="left" width="64" style="margin-right: 16px; margin-bottom: 8px;">

**Push code onto a CircuitPython or MicroPython board, probe its identity, and flash firmware — from your laptop.**

Programmatic Python API + a `chumicro-deploy` CLI.  Pluggable file sources (in-memory, directory walk, AST-driven import graph), pluggable transport modes (RAM mode for fast iteration, flash mode for persistence), and an interactive recovery layer that classifies failures (port busy, drive ejected, raw REPL stuck, macOS FSKit wedge, source traceback) and walks you through the fix.

<br clear="left">

> Part of the [ChuMicro](https://github.com/ChuMicro/ChuMicro) family — small, focused Python libraries for microcontrollers and laptops. [See all libraries.](https://github.com/ChuMicro/ChuMicro#whats-in-the-box)
> This is a [workbench tool](https://github.com/ChuMicro/ChuMicro/blob/main/docs/contributing/workbench.md) — runs on your laptop, not on the board.

## Installation

```bash
pip install chumicro-deploy
```

`pyserial` (CircuitPython transport) and `mpremote` (MicroPython transport) come along as dependencies.  On macOS and Linux you'll also need `rsync` available on `$PATH` for flash-mode deploys to the CIRCUITPY USB drive — install via `brew install rsync` (macOS Homebrew if not already shipped), `apt-get install rsync` (Debian/Ubuntu), `dnf install rsync` (Fedora), `pacman -S rsync` (Arch), `apk add rsync` (Alpine), or `zypper install rsync` (openSUSE).  Native Windows isn't currently supported (raises `WindowsNotSupportedError` on import); WSL2 works.

<details>
<summary>Experimental (pre-release) versions and channel switching</summary>

Pre-release builds are published automatically when the package version is bumped.

```bash
pip install chumicro-deploy-experimental
```

</details>

## Quick example

Deploy a one-liner to a connected MicroPython board and read its output back:

```python
from chumicro_deploy import Device, Deployer, FileMapSource

device = Device(
    transport="micropython",
    address="/dev/cu.usbmodem14101",  # see `chumicro-deploy probe --address ...` to identify
    deploy_mode="ram",                # no flash wear, no CIRCUITPY drive needed
)
source = FileMapSource(
    {"/main.py": "import sys\nprint(f'hello from {sys.implementation.name}')"},
    entrypoint="/main.py",
)

result = Deployer(device).deploy(source)
print(result.execute_output)  # → "hello from micropython"
```

For a workspace project that already has a `devices.yml`, swap the `Device(...)` constructor for `chumicro_deploy.config.default.load_devices_yml("devices.yml", device_id="my-board")`.

## What's included

### Programmatic API

| Symbol | Description |
|---|---|
| `Device(transport, address, deploy_mode, ...)` | Configure a target board.  Build explicitly or via `Device.from_dict(...)`; or load a registry via `load_devices_yml(...)` / `load_device_registry(...)` |
| `Deployer(device)` | Push a `FileSource` onto the board and execute the entrypoint.  Returns a `DeployResult` with success / output / traceback |
| `Deployer.deploy_diff(source, *, wipe=False, ...)` | Same shape, but first lists in-scope files on the device and deletes any that aren't in the new payload |
| `InteractiveDeployer(deployer)` | Wrapper that classifies transport failures, surfaces a `RecoveryPlan`, and prompts the user to retry.  Default for both CLIs (`--non-interactive` to opt out) |
| `FileMapSource(files, entrypoint)` | In-memory `dict[device_path, bytes]` source — for generated payloads or one-off scripts |
| `DirectorySource(directory, entrypoint, resource_prefix)` | Walk a host directory and ship every file under it |
| `ImportGraphSource(entrypoint, search_paths, device_entrypoint)` | AST-walk the entrypoint and ship only transitively-imported modules |
| `probe_device(device)` → `DeviceInfo` | Identify a connected board (runtime, version, machine string, CPU UID) |
| `flash_firmware(url, device, reflash_method, ...)` | Download + apply firmware via UF2 (Pi Pico family) or esptool (ESP32 family) |
| `resolve_firmware_url(board_id, runtime, version)` | Build the canonical Adafruit / micropython.org download URL |
| `classify_deploy_failure(error)` → `DeployFailureKind` | Standalone classifier for building your own failure-handling on top of `Deployer` |
| `detect_fskit_wedge()` → `bool` | macOS-only probe for the FSKit / DiskArbitration wedge that can leave CIRCUITPY drives unmountable |

### CLI subcommands

`python -m chumicro_deploy <subcommand>` (or just `chumicro-deploy <subcommand>` after `pip install`).  Each accepts `--devices-file devices.yml --device <id>` instead of `--transport` + `--address` for workspace-style invocations.

| Subcommand | What it does |
|---|---|
| `probe` | Identify a board's runtime / version / machine / UID.  `--json` for machine-readable output |
| `deploy` | Push a `--directory` or `--file-map` to the board and run the `--entrypoint`.  Interactive coaching by default; `--non-interactive` for CI |
| `flash` | Download + apply firmware.  `--method uf2` or `--method esptool`; `--erase` to wipe user partitions; `--non-interactive` to fail instead of prompting on bootloader-entry |
| `resolve-firmware-url` | Print the canonical firmware URL for a `--board-id` + `--runtime` + `--version` (no board needed) |

### Testing fakes

| Symbol | What it does |
|---|---|
| `FakeTransport` | Implements `TransportProtocol` + `ExtendedTransportProtocol` for unit-testing `Deployer` orchestration without real hardware |
| `FakeSerialPort` | Scriptable pyserial substitute for `CircuitpythonTransport` tests |
| `FakeTime` | Deterministic clock for `Deployer` / transport / `flash_firmware` tests |

### Status

> Pre-alpha.  Decision 0029 Phase 1 complete: host-side device transports, `Device` / `Deployer` facade, `FileSource` pluggability, `probe_device`, `flash_firmware` (UF2 + esptool), the `chumicro-deploy` CLI, and the `InteractiveDeployer` recovery layer are all shipped and hardware-verified on ESP32-S2, ESP32-S3, and Pi Pico W across CircuitPython and MicroPython.  See [the project-workspace workstream](https://github.com/ChuMicro/ChuMicro/blob/main/plans/workstreams/project-workspace.md) for what's ahead.

## Companion: chumicro-repl

[`chumicro-repl`](../repl/) is the sister workbench tool for opening interactive serial sessions and tailing the friendly REPL after a deploy.  Both packages consume the same `devices.yml` schema (owned here in `chumicro_deploy.config.default`), so a single workspace file points both at the same boards.  Use `chumicro_repl.tail(device, seconds)` to follow a deploy and fail-fast on a traceback; use `chumicro_repl.ReplSession(device)` for headless test fixtures over raw REPL.

## Examples

| Example | What it shows |
|---|---|
| `programmatic_deploy.py` | Minimal `Deployer` + `DirectorySource` walkthrough |
| `file_map_deploy.py` | Multi-file payload built in memory via `FileMapSource` |
| `import_graph_deploy.py` | `ImportGraphSource` AST-walk — ships only modules the entrypoint actually imports |
| `demo_recovery_hand_holding.py` | Interactive walk through every `DeployFailureKind` recovery scenario against real hardware |

## Developing this library

Host-side tests live in `tests/`; real-board functional tests live in `functional_tests/`.

```bash
python scripts/run.py test --libraries deploy
python scripts/run.py test-workbench-functional --workbench deploy
```

Before running device tests, generate local board config files with `python scripts/run.py setup`, then fill in `devices.yml`. See the [contributing guide](https://github.com/ChuMicro/ChuMicro/blob/main/CONTRIBUTING.md) and the [device testing guide](https://github.com/ChuMicro/ChuMicro/blob/main/docs/contributing/device-testing.md) for the full workflow.

## Docs

📖 **[Stable docs](https://chumicro.github.io/ChuMicro/deploy/stable/)** · **[Experimental docs](https://chumicro.github.io/ChuMicro/deploy/experimental/)**

## Find this library

- **PyPI:** [chumicro-deploy](https://pypi.org/project/chumicro-deploy/)
- **Source:** [workbench/deploy](https://github.com/ChuMicro/ChuMicro/tree/main/workbench/deploy)

## License

[MIT](https://github.com/ChuMicro/ChuMicro/blob/main/LICENSE)
