# chumicro-deploy

<img src="https://raw.githubusercontent.com/ChuMicro/ChuMicro/main/support/docs/chumicro_tip.png"
align="left" width="64" style="margin-right: 16px; margin-bottom: 8px;">

**Push code onto a CircuitPython or MicroPython board, probe its identity, and flash firmware — from your laptop.**

Programmatic Python API + a `chumicro-deploy` CLI.  Pluggable file sources (in-memory, directory walk, AST-driven import graph), pluggable transport modes (RAM mode for fast iteration, flash mode for persistence), and an interactive recovery layer that classifies failures (port busy, drive ejected, raw REPL stuck, macOS FSKit wedge, source traceback) and walks you through the fix.

<br clear="left">

> Part of the [ChuMicro](https://github.com/ChuMicro/ChuMicro) family — small, focused Python libraries for microcontrollers and laptops. [Browse all workbench tools.](https://github.com/ChuMicro/ChuMicro/tree/main/workbench)
> This is a [workbench tool](https://github.com/ChuMicro/ChuMicro/blob/main/docs/contributing/workbench.md) — runs on your laptop, not on the board.

## Install

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

result = Deployer(device).deploy_diff(source)
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
| `RecoveringDeployer(deployer, *, prompt=None, max_attempts=3)` | Wraps `Deployer` with failure classification and a `RecoveryPlan`.  Pass `prompt=input` for an interactive retry loop; default `prompt=None` reports once and re-raises.  Both CLIs use the interactive form by default (`--non-interactive` to opt out) |
| `FileMapSource(files, entrypoint)` | In-memory `dict[device_path, bytes]` source — for generated payloads or one-off scripts |
| `DirectorySource(directory, entrypoint, resource_prefix)` | Walk a host directory and ship every file under it |
| `ImportGraphSource(entrypoint, search_paths, device_entrypoint)` | AST-walk the entrypoint and ship only transitively-imported modules |
| `probe_device(device)` → `DeviceInfo` | Identify a connected board (runtime, version, machine string, CPU UID) |
| `flash_firmware(url, device, reflash_method, ...)` | Download + apply firmware via UF2 (Pi Pico family) or esptool (ESP32 family) |
| `resolve_firmware_url(board_id, runtime, version)` | Build the canonical Adafruit / micropython.org download URL |
| `classify_deploy_failure(error)` → `DeployFailureKind` | Standalone classifier for building your own failure-handling on top of `Deployer` |
| `detect_fskit_wedge()` → `bool` | macOS-only probe for the FSKit / DiskArbitration wedge that can leave CIRCUITPY drives unmountable |

### `devices.yml` writer surface

`chumicro_deploy.config.devices_yaml` (separate submodule) — round-trip read/write of the device registry with comments and key order preserved, three-zone classification (user-owned / hardware-once / probed-always).  This is what `chumicro-workspace add-device` and friends sit on; consumers building their own onboarding flow against `devices.yml` use this surface directly.

| Symbol | What it does |
|---|---|
| `load_devices(path)` → `CommentedMap` | Parse with comments + key order preserved (returns ruamel `CommentedMap`, distinct from the typed reader at `chumicro_deploy.config.default.load_devices`) |
| `dump_devices(data, path)` | Atomic write back via tempfile + rename |
| `find_device(data, device_id)` / `list_device_ids(data)` | Read-only lookups against the loaded document |
| `add_device(data, *, device_id, runtime, address, hardware, ...)` | Append a new entry; raises `DeviceAlreadyExistsError` on id collision |
| `update_device_address(data, device_id, new_address)` | Silent refresh — address is the probed-always zone |
| `update_device_firmware_version(data, device_id, new_version)` | Silent refresh of the cached `firmware_version` |
| `update_device_hardware(data, device_id, *, force=False, **fields)` | Hardware-once zone — raises `HardwareOverwriteError` on a value change unless `force=True` |
| `rename_device(data, old_id, new_id)` / `set_runtime_default(data, runtime, device_id)` | Higher-level mutations |
| `USER_OWNED_FIELDS` / `PROBED_ALWAYS_FIELDS` / `HARDWARE_ONCE_FIELDS` / `HARDWARE_BLOCK_ZONES` | The canonical zone classification — single source of truth that the typed reader's `_KNOWN_KEYS` derives from |

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

## Where this fits

Leaf — no upstream ChuMicro deps (uses third-party `pyserial` and `mpremote` for transport).  Sister of [`chumicro-repl`](https://github.com/ChuMicro/ChuMicro/tree/main/workbench/repl), substrate for [`chumicro-workspace`](https://github.com/ChuMicro/ChuMicro/tree/main/workbench/workspace) and [`chumicro-pytest-device`](https://github.com/ChuMicro/ChuMicro/tree/main/workbench/pytest-device).

## Companion: chumicro-repl

[`chumicro-repl`](https://github.com/ChuMicro/ChuMicro/tree/main/workbench/repl) is the sister workbench tool for opening interactive serial sessions and tailing the friendly REPL after a deploy.  Both packages consume the same `devices.yml` schema (owned here in `chumicro_deploy.config.default`), so a single workspace file points both at the same boards.  Use `chumicro_repl.tail(device, seconds)` to follow a deploy and fail-fast on a traceback; use `chumicro_repl.ReplSession(device)` for headless test fixtures over raw REPL.

## Examples

| Example | What it shows |
|---|---|
| `programmatic_deploy.py` | Minimal `Deployer` + `DirectorySource` walkthrough |
| `file_map_deploy.py` | Multi-file payload built in memory via `FileMapSource` |
| `import_graph_deploy.py` | `ImportGraphSource` AST-walk — ships only modules the entrypoint actually imports |
| `demo_recovery_hand_holding.py` | Interactive walk through every `DeployFailureKind` recovery scenario against real hardware |

## Contributing

Working on `chumicro-deploy` itself?  Clone the [mono-repo](https://github.com/ChuMicro/ChuMicro) if you haven't already — the rest of the workflow assumes you're inside that workspace.

```bash
pip install -e .[test]
pytest tests/                  # host-side tests
pytest functional_tests/       # on-device tests (needs a board registered in devices.yml)
```

Register a board before running functional tests: `chumicro-workspace add-device <id> --address <port>` (or hand-write a `devices.yml` entry).

## Docs

📖 **[Stable docs](https://chumicro.github.io/ChuMicro/deploy/stable/)** · **[Experimental docs](https://chumicro.github.io/ChuMicro/deploy/experimental/)**

## Find this library

- **PyPI:** [chumicro-deploy](https://pypi.org/project/chumicro-deploy/)
- **Source:** [workbench/deploy](https://github.com/ChuMicro/ChuMicro/tree/main/workbench/deploy)

## License

[MIT](https://github.com/ChuMicro/ChuMicro/blob/main/LICENSE)
