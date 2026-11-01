# chumicro-deploy

<img src="https://raw.githubusercontent.com/ChuMicro/ChuMicro/main/support/docs/chumicro_tip.png"
align="left" width="64" style="margin-right: 16px; margin-bottom: 8px;">

**Copy Python code to a CircuitPython or MicroPython board and run it, install new firmware, or ask a board which firmware it runs, all from your laptop.**

`chumicro-deploy` is the lower-level tool under [`chumicro-workspace`](https://github.com/ChuMicro/ChuMicro/tree/main/workbench/workspace).  Inside a ChuMicro workspace, `chumicro-workspace deploy` and `chumicro-workspace install-firmware` call this package and find each board by its name in `devices.yml`.  `chumicro-deploy` serves the work outside a workspace: a folder of code sent to a board by its serial port, a CI job, or a Python script that runs the deploy itself.  When a step fails, the tool names the cause, such as another app holding the serial port or a missing CIRCUITPY drive, and lists the steps that fix it.

<br clear="left">

> Part of the [ChuMicro](https://github.com/ChuMicro/ChuMicro) family: small, focused Python libraries for microcontrollers and laptops. [Browse all workbench tools.](https://github.com/ChuMicro/ChuMicro/tree/main/workbench)
> This is a [workbench tool](https://github.com/ChuMicro/ChuMicro/blob/main/docs/contributing/workbench.md): it runs on your laptop, not on the board.

## Three commands

Each command takes the board's runtime and serial port.  On macOS, `ls /dev/cu.usbmodem*` lists the ports.  On Linux, `ls /dev/ttyACM*` lists them.  The entry that appears when the board is plugged in is the board's port.

```bash
# Ask the board which firmware it runs.
chumicro-deploy probe --transport circuitpython --address /dev/cu.usbmodem1101

# Copy the my_app folder to the board and run my_app/code.py.
chumicro-deploy deploy --transport circuitpython --address /dev/cu.usbmodem1101 \
    --directory ./my_app --entrypoint /code.py

# Install CircuitPython 10.1.4 on a Raspberry Pi Pico W.
chumicro-deploy flash-firmware --transport circuitpython --address /dev/cu.usbmodem1101 \
    --url https://downloads.circuitpython.org/bin/raspberry_pi_pico_w/en_US/adafruit-circuitpython-raspberry_pi_pico_w-en_US-10.1.4.uf2
```

`deploy` runs the code from the board's memory by default and leaves the files stored on the board alone.  `--deploy-mode flash` writes the files to the board instead, so the code runs again after a reset.  A folder that holds any file other than `.py` switches to flash mode on its own.  A flash deploy deletes every board file outside the folder, `settings.toml` included, unless `--no-wipe` is passed.

`chumicro-deploy resolve-firmware-url` prints the CircuitPython download link for a board and version.  `--help` after any command lists its options.

The [user guide](https://chumicro.com/ChuMicro/deploy/stable/guide/) covers each command, `devices.yml`, failure recovery, and the Python API.

## Install

```bash
pip install chumicro-deploy
```

`pyserial` and `mpremote` install with it.  A flash-mode deploy to CircuitPython copies files with `rsync`.  macOS ships `rsync`.  On Linux, `sudo apt-get install rsync` or the distribution's equivalent installs it.  On native Windows, `Deployer` and `probe_device` raise `WindowsNotSupportedError`.  WSL2 works.

<details>
<summary>Experimental (pre-release) versions and channel switching</summary>

Pre-release builds are published automatically when the package version is bumped.

```bash
pip install chumicro-deploy-experimental
```

</details>

## Deploy from Python

The same deploy runs from a script.  This one sends a one-line program to a MicroPython board and prints what the board printed:

```python
from chumicro_deploy import Device, Deployer, FileMapSource

device = Device(
    transport="micropython",
    address="/dev/cu.usbmodem14101",
    deploy_mode="ram",                # run from memory, write nothing to the board
)
source = FileMapSource(
    {"/main.py": "import sys\nprint(f'hello from {sys.implementation.name}')"},
    entrypoint="/main.py",
)

result = Deployer(device).deploy_diff(source)
print(result.execute_output)  # hello from micropython
```

A workspace that already has a `devices.yml` builds the `Device` from it: `chumicro_deploy.config.default.load_devices_yml("devices.yml", device_id="my-board")`.

## What's included

### Python API

| Symbol | What it does |
|---|---|
| `Device(transport, address, deploy_mode, ...)` | Holds one board's runtime, serial port, and deploy mode.  `Device.from_dict(...)`, `load_devices_yml(...)`, and `load_device_registry(...)` build it from data |
| `Deployer(device)` | Runs deploys against one board |
| `Deployer.deploy_diff(source, *, clean=True, wipe=False, ...)` | Copies a `FileSource` to the board, deletes board files outside it, and runs the entry file.  Returns a `DeployResult` with the board's output and any traceback.  `clean=False` deletes old files only in `/lib` and the entry files, and `wipe=True` erases the filesystem first |
| `RecoveringDeployer(deployer, *, prompt=None, max_attempts=3)` | Wraps a `Deployer`.  On a failure it prints the cause and the fix steps, then re-raises.  `prompt=input` adds an Enter-to-retry loop, which the `chumicro-deploy deploy` command uses |
| `FileMapSource(files, entrypoint)` | Sends a `dict` of board paths to file contents, for generated code or a one-off script |
| `DirectorySource(directory, entrypoint, resource_prefix)` | Sends every file under a folder |
| `ImportGraphSource(entrypoint, search_paths, device_entrypoint)` | Reads the entry file's imports and sends only the modules they reach |
| `probe_device(device)` → `DeviceInfo` | Reports a board's runtime, version, machine string, and CPU id |
| `flash_firmware(url, device, reflash_method, ...)` | Downloads firmware and installs it through the UF2 bootloader drive (Pi Pico family) or esptool (ESP32 family) |
| `resolve_firmware_url(board_id, runtime, version)` | Builds a CircuitPython download URL.  `runtime="micropython"` raises `UnresolvedFirmwareError` |
| `classify_deploy_failure(error)` → `DeployFailureKind` | Names the failure behind a deploy exception, for code that handles failures itself |
| `detect_fskit_wedge()` → `bool` | macOS only.  Reports whether the FSKit filesystem service is stuck, which keeps CIRCUITPY drives from mounting |

### `devices.yml` editing

`chumicro_deploy.config.devices_yaml` reads and writes `devices.yml` while keeping its comments and key order.  `chumicro-workspace add-device` and the other board-registry commands use it.  It sorts every field into three zones: fields the user owns, hardware fields written once, and fields a probe refreshes every time.

| Symbol | What it does |
|---|---|
| `read_devices_yml_template()` → `str` | Returns the text of an empty `devices.yml`, for writing a fresh file |
| `load_devices(path)` → `CommentedMap` | Parses the file with comments and key order kept.  The typed reader with the same name lives at `chumicro_deploy.config.default.load_devices` |
| `dump_devices(data, path)` | Writes the file back atomically through a temporary file and a rename |
| `find_device(data, device_id)` / `list_device_ids(data)` | Looks up entries in the loaded document |
| `add_device(data, *, device_id, runtime, address, hardware, ...)` | Appends an entry.  Raises `DeviceAlreadyExistsError` when the id is taken |
| `remove_device(data, device_id)` → `CommentedMap` | Drops an entry, clears any `defaults:` key that named it, and returns the removed entry.  Raises `DeviceNotFoundError` when no entry matches |
| `update_device_address(data, device_id, new_address)` | Replaces the serial port, a field a probe refreshes |
| `update_device_firmware_version(data, device_id, new_version)` | Replaces the cached `firmware_version` |
| `update_device_hardware(data, device_id, *, force=False, **fields)` | Writes hardware fields.  Raises `HardwareOverwriteError` on a changed value unless `force=True` |
| `rename_device(data, old_id, new_id)` / `set_runtime_default(data, runtime, device_id)` | Renames an entry, or picks the default board for a runtime |
| `USER_OWNED_FIELDS` / `PROBED_ALWAYS_FIELDS` / `HARDWARE_ONCE_FIELDS` / `HARDWARE_BLOCK_ZONES` | Name the fields in each zone |

### Commands

`chumicro-deploy COMMAND` and `python -m chumicro_deploy COMMAND` run the same tool.  `probe`, `deploy`, and `flash-firmware` take either `--transport` and `--address`, or `--devices-file devices.yml --device ID`.

| Command | What it does |
|---|---|
| `probe` | Prints the board's runtime, version, machine string, and CPU id.  `--json` prints one JSON object |
| `deploy` | Copies a `--directory` or `--file-map` to the board and runs `--entrypoint`.  A fixable failure waits for Enter and retries.  `--non-interactive` makes one attempt, for CI |
| `flash-firmware` | Downloads firmware from `--url` and installs it.  The `.uf2` or `.bin` ending picks uf2 or esptool unless `--method` says otherwise.  esptool erases the whole flash first, CIRCUITPY drive and saved wifi credentials included, unless `--no-erase` is passed |
| `resolve-firmware-url` | Prints the CircuitPython download link for `--board-id` and `--version`.  Needs no board |

### Testing fakes

| Symbol | What it does |
|---|---|
| `FakeTransport` | Stands in for a board transport, so tests drive `Deployer` with no hardware |
| `FakeSerialPort` | Scriptable `serial.Serial` replacement for `CircuitpythonTransport` tests |
| `FakeTime` | Clock that advances only when told, for `Deployer`, transport, and `flash_firmware` tests |

## Where this fits

`chumicro-deploy` has no ChuMicro dependencies.  `pyserial` and `mpremote` carry the serial traffic.  [`chumicro-workspace`](https://github.com/ChuMicro/ChuMicro/tree/main/workbench/workspace) and [`chumicro-pytest-device`](https://github.com/ChuMicro/ChuMicro/tree/main/workbench/pytest-device) build on it.

[`chumicro-repl`](https://github.com/ChuMicro/ChuMicro/tree/main/workbench/repl) opens the board's REPL and follows its output after a deploy.  Both tools read the same `devices.yml`, whose format this package defines in `chumicro_deploy.config.default`.  `chumicro_repl.tail(device, seconds)` follows a deploy and stops on a traceback.  `chumicro_repl.ReplSession(device)` runs code on the board from a test.

## Examples

| Example | What it shows |
|---|---|
| `programmatic_deploy.py` | `Deployer` and `DirectorySource` sending a folder |
| `file_map_deploy.py` | A multi-file payload built in memory with `FileMapSource` |
| `import_graph_deploy.py` | `ImportGraphSource` sending only the modules the entry file imports |
| `demo_recovery_hand_holding.py` | An interactive walk through each failure the recovery coaching handles, on real boards |

## Contributing

Issues, bug reports, and pull requests are welcome, and so is "I ran it on this board and here's what happened", some of the most useful feedback a hardware project can get.  Development happens in the [ChuMicro repository](https://github.com/ChuMicro/ChuMicro), whose contributing guide covers setup and the test workflow.

## Docs

📖 **[Stable docs](https://chumicro.com/ChuMicro/deploy/stable/)** · **[Experimental docs](https://chumicro.com/ChuMicro/deploy/experimental/)**

## Find this library

- **PyPI:** [chumicro-deploy](https://pypi.org/project/chumicro-deploy/)
- **Source:** [workbench/deploy](https://github.com/ChuMicro/ChuMicro/tree/main/workbench/deploy)

## License

[MIT](https://github.com/ChuMicro/ChuMicro/blob/main/LICENSE)
