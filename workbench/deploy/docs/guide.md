# User Guide

`chumicro-deploy` copies Python code from your laptop to a CircuitPython or MicroPython board, runs it, and installs firmware.  Inside a ChuMicro workspace, [`chumicro-workspace`](https://chumicro.com/ChuMicro/workspace/stable/) runs the same steps and finds each board by name.

## Install

```bash
pip install chumicro-deploy
```

The install puts a `chumicro-deploy` command on your `PATH`.  The board needs CircuitPython or MicroPython firmware and nothing else.  [Install firmware](#install-firmware) covers a board that runs neither.

## Find the board's serial port

Every command reaches the board through its USB serial port.  On macOS, `ls /dev/cu.*` lists the ports.  A board with native USB shows up there as `/dev/cu.usbmodem…`.  On Linux, `ls /dev/ttyACM* /dev/ttyUSB*` lists them.  Run the listing with the board unplugged and again with it plugged in: the new entry is the board.

Another program with the port open blocks every command.  Thonny, Mu, the Arduino IDE serial monitor, a `screen` session, and `chumicro-repl` each hold the port until they quit.

## Check the board with `probe`

`probe` asks the board which firmware it runs:

```bash
chumicro-deploy probe --transport circuitpython --address /dev/cu.usbmodem1101
```

```text
runtime: circuitpython
version: 10.1.4
machine: Raspberry Pi Pico W with rp2040
uid: E6614C311B4C6E2F
```

`--transport` names the firmware you expect, `circuitpython` or `micropython`, and picks how the tool talks to the board.  `--json` prints the same fields as one JSON object.  A board running other firmware, such as an Arduino sketch, fails the probe.  [Install firmware](#install-firmware) puts Python on it.

## Deploy a folder

`deploy` copies a folder to the board and runs one file from it:

```bash
chumicro-deploy deploy --transport circuitpython --address /dev/cu.usbmodem1101 \
    --directory ./my_app --entrypoint /code.py
```

`--entrypoint` is the board path of the file to run.  `./my_app/code.py` lands at `/code.py`, and `./my_app/lib/helper.py` lands at `/lib/helper.py`.  CircuitPython runs `code.py` at startup, and MicroPython runs `main.py`.  The command prints progress on stderr and the board's output on stdout:

```text
[ 0.0%] connecting
[10.0%] listing in-scope
[30.0%] staging
[90.0%] executing
[100.0%] done
hello from my_app
```

The deploy skips `__pycache__`, `.git`, `.DS_Store`, `.pytest_cache`, and `.mypy_cache`.  It also skips a module that sets `__chumicro_test_support__ = True`, such as a library's `testing.py` fakes, and a `.py` file whose `__chumicro_runtimes__` marker leaves out the board's runtime.  `--target-runtime` picks a different runtime for that filter.  Every `.py` file loses its docstrings and comments on the way, so the board runs a smaller copy of your source.

### ram mode and flash mode

`--deploy-mode` picks where the files go.

- **`ram`**, the default, runs the code from the board's memory and leaves the files stored on the board alone.  A reset brings back whatever the board ran before.  It suits trying code out.
- **`flash`** writes the files to the board's filesystem, so the code runs again after every reset.  CircuitPython receives the files on its CIRCUITPY drive, and MicroPython receives them over serial.

A folder that holds any file other than `.py`, such as a `settings.toml` or an image, switches the deploy to flash mode on its own, because ram mode cannot reliably carry a data file to the board.  The command prints a `switching to flash mode` line that names the files.

Flash mode suits code that never finishes, such as a `while True:` loop.  With `/code.py` on CircuitPython or `/main.py` on MicroPython as the entry file, the board restarts into the new code.  The command prints its output for 10 seconds, then returns and leaves the code running.  On CircuitPython, `--tail-seconds` changes that window.  `--tail-seconds 30` waits for code that prints its first line after a slow wifi connect.  `--tail-seconds 0` returns right after the restart.

### What a deploy deletes

A flash deploy makes the board hold exactly the folder you sent.  It deletes every other file on the board, `settings.toml` included, and keeps only `boot.py`, `boot_out.txt`, and `_chu_kv.msgpack`.  A file you keep on the board by hand, such as a `settings.toml` with wifi credentials, belongs in the folder you deploy.

Two flags change what goes:

| Flag | What the deploy deletes |
|---|---|
| none | Every board file outside the payload, except `boot.py`, `boot_out.txt`, and `_chu_kv.msgpack` |
| `--no-wipe` | Old files only in `/lib` and in `/code.py`, `/main.py`, `/active.py`, and `/runtime_config.msgpack`.  Every other board file stays |
| `--wipe` | The whole filesystem before copying, `boot.py`, `boot_out.txt`, and `_chu_kv.msgpack` included.  It recovers a board whose filesystem is corrupt |

A ram deploy writes nothing to the board, so it deletes nothing and `--wipe` has no effect.  The command prints `removed stale <path>` on stderr for each file it deleted.

### Send a file map instead of a folder

`--file-map` takes a JSON file that maps board paths to file contents, for code a script generated:

```json
{
  "/code.py": "from greeter import greet\nprint(greet('world'))\n",
  "/lib/greeter.py": "def greet(name):\n    return 'hi ' + name\n"
}
```

```bash
chumicro-deploy deploy --transport circuitpython --address /dev/cu.usbmodem1101 \
    --file-map payload.json --entrypoint /code.py
```

The file map ships exactly the paths it names, so `--resource-prefix` and `--target-runtime` have no effect on it.

## Name boards in `devices.yml`

A `devices.yml` file records each board's runtime, port, and deploy mode under a name, so a command names the board instead of repeating its details:

```yaml
defaults:
  circuitpython: back-porch
devices:
  - id: back-porch
    runtime: circuitpython
    address: /dev/cu.usbmodem1101
    deploy_mode: flash
```

```bash
chumicro-deploy probe --devices-file devices.yml --device back-porch
chumicro-deploy deploy --devices-file devices.yml --device back-porch \
    --directory ./my_app --entrypoint /code.py
```

`--devices-file` takes the runtime, port, baud rate, and deploy mode from the entry.  The command then ignores `--transport`, `--address`, `--baudrate`, and `--deploy-mode`.  An entry without `deploy_mode` falls back to `defaults.deploy_mode` and then to `flash`.  Leaving out `--device` picks the board named under `defaults:`, which works when `defaults:` names a board for one runtime only.  `chumicro-workspace add-device` probes a board and writes its entry.

## Install firmware

`flash-firmware` downloads a firmware file and installs it, replacing whatever the board runs now.  It puts the board into its bootloader itself and asks you to hold the board's BOOT button only when that fails.

### Raspberry Pi Pico and other UF2 boards

A UF2 board takes a `.uf2` file.  `resolve-firmware-url` prints the CircuitPython download link for a board id and version, with no board plugged in:

```bash
chumicro-deploy resolve-firmware-url \
    --board-id raspberry_pi_pico_w --runtime circuitpython --version 10.1.4
```

```text
https://downloads.circuitpython.org/bin/raspberry_pi_pico_w/en_US/adafruit-circuitpython-raspberry_pi_pico_w-en_US-10.1.4.uf2
```

```bash
chumicro-deploy flash-firmware \
    --transport circuitpython --address /dev/cu.usbmodem1101 \
    --url https://downloads.circuitpython.org/bin/raspberry_pi_pico_w/en_US/adafruit-circuitpython-raspberry_pi_pico_w-en_US-10.1.4.uf2
```

The board id is the one circuitpython.org shows on the board's download page.  A MicroPython link carries a build date the tool cannot know, so `resolve-firmware-url` exits with an error for `--runtime micropython`.  The micropython.org download page for the board lists its links.

### ESP32 boards

An ESP32-family board takes a `.bin` file, which `flash-firmware` writes with esptool over serial:

```bash
chumicro-deploy flash-firmware \
    --transport micropython --address /dev/cu.usbmodem211101 \
    --url https://micropython.org/resources/firmware/LOLIN_S2_MINI-20260406-v1.28.0.bin \
    --offset 0x1000
```

- **`--offset`** is the flash address where the image starts.  CircuitPython `.bin` files start at `0x0`, the default.  MicroPython on ESP32 and ESP32-S2 starts at `0x1000`.  The micropython.org download page for each board lists its offset.  A wrong offset writes over the bootloader and leaves the board unbootable until a manual reflash, with BOOT held while RESET is tapped.  The tool cannot tell which offset a `.bin` file needs.
- **Erase.**  esptool erases the whole flash before writing, which empties the CIRCUITPY drive and forgets saved wifi credentials.  `--no-erase` keeps them during an in-place upgrade.

The `.uf2` or `.bin` ending of `--url` picks the method.  `--method uf2` or `--method esptool` sets it for a link with neither ending.  `--bootloader-drive /Volumes/RPI-RP2` points a UF2 install at a bootloader drive the automatic search misses.

## When a step fails

A `deploy` that hits a transport failure names the failure, prints the steps that fix it, and waits for Enter to retry.  An unplugged board looks like this:

```text
[chumicro-deploy] Attempt 1/3 failed: port_unavailable
[chumicro-deploy] The serial port is unavailable.
[chumicro-deploy] Underlying error: <the error the serial port raised>
[chumicro-deploy] Try this:
  - Check that the board is plugged into USB.
  - Close any app that may be holding the port: Mu, Thonny, screen/minicom, another mpremote, PyCharm or VS Code serial console.
  - If the port still does not appear, tap the board's RESET button and wait 2 to 3 seconds for re-enumeration.
[chumicro-deploy] Fix the condition above and press Enter to retry (attempt 2/3), or type 'quit' to abort:
```

Enter retries, up to three attempts in all.  A reply that starts with `q`, `a`, or `e`, such as `quit`, stops and exits 1.  When another process holds the port, the report lists its process id and command line.  A stale `chumicro-deploy` or `mpremote` process from an earlier run gets a `kill <pid>` line to paste.

Some failures need a fix before any retry can work, such as a board that needs firmware or code that raised a traceback.  For those the command prints the steps once and exits 1 without asking.  [Failure kinds](#failure-kinds) lists every failure, its first fix, and whether the command offers a retry.

### Scripts and CI

`--non-interactive` makes one attempt with no prompt.  A failure prints the same report and exits 1, so a script or CI job never waits on input.  `flash-firmware --non-interactive` exits with an error instead of asking for the BOOT button.

## Watch the board with chumicro-repl

A flash deploy returns once its capture window closes.  Code that loops forever keeps printing after that.  [`chumicro-repl`](https://chumicro.com/ChuMicro/repl/stable/) follows the board's output and opens its REPL:

```bash
chumicro-repl --address /dev/cu.usbmodem1101 --tail 30
chumicro-repl --address /dev/cu.usbmodem1101
```

The first command prints 30 seconds of output and exits 1 on a traceback.  The second opens the board's `>>>` prompt.  `chumicro-workspace repl --device back-porch` opens the same session by the board's name in `devices.yml`.

## Use it from Python

Every command is a thin wrapper over a Python call, so a script runs the same deploy.

### Configure a board: `Device`

A `Device` holds one board's connection details.  It is a frozen dataclass that every other call takes.

```python
from chumicro_deploy import Device

device = Device(
    transport="micropython",          # or "circuitpython"
    address="/dev/cu.usbmodem14101",  # serial port
    baudrate=115200,
    deploy_mode="ram",                # "ram" or "flash", default "flash"
    entrypoint_name=None,             # None means code.py on CircuitPython, main.py on MicroPython
    resource_prefix="/lib",           # board folder for files that are not the entry file
)
```

`Device` raises `ValueError` for a `transport` other than `"circuitpython"` or `"micropython"`, and for a `deploy_mode` other than `"ram"` or `"flash"`.  The Python default for `deploy_mode` is `"flash"`, while the `deploy` command defaults to `ram`.

### Pick a `FileSource`

A `FileSource` supplies the files and names the entry file.  Any object with `.files() -> dict[str, bytes]` and `.entrypoint() -> str` qualifies, because `FileSource` is a `@runtime_checkable` [Protocol](https://typing.python.org/en/latest/library/typing.html#typing.Protocol).  Three come built in.

`FileMapSource` takes a `dict` of board paths to contents.  A value can be `str`, encoded as UTF-8, or `bytes`.  The entry file must be one of the keys.

```python
from chumicro_deploy import FileMapSource

source = FileMapSource(
    {
        "/main.py": "from greeter import greet\nprint(greet('world'))\n",
        "/lib/greeter.py": "def greet(name): return f'hi {name}'\n",
    },
    entrypoint="/main.py",
)
```

`DirectorySource` sends every file under a folder.  The entry file is a board path: `/main.py` means `my_app/main.py`.

```python
from pathlib import Path
from chumicro_deploy import DirectorySource

source = DirectorySource(
    Path("my_app"),
    entrypoint="/main.py",
    resource_prefix="/",          # board folder the files land in
    excluded_names=None,          # None skips __pycache__, .DS_Store, .git, .pytest_cache, .mypy_cache
)
```

`ImportGraphSource` reads the entry file's `import` statements, follows them through `search_paths`, and sends only the modules they reach:

```python
from pathlib import Path
from chumicro_deploy import ImportGraphSource

source = ImportGraphSource(
    entrypoint=Path("my_app/main.py"),
    search_paths=[Path("my_app"), Path("packages")],
    extra_modules=["dynamically_imported_thing"],
    device_entrypoint="/code.py",     # default
    resource_prefix="/lib",           # default
)
```

An import of a board built-in, such as `gc`, `time`, or `board`, needs no file and stays out of the payload.  `chumicro_deploy.import_allowlist.DEVICE_BUILTIN_MODULES` lists the built-ins.  Any other import that matches no file raises `UnresolvedImportError` from the constructor and names the file that imports it, so a typo or a missing search path fails on your laptop before the board sees an `ImportError`.  An import inside `try` / `except ImportError` counts as optional and never fails the build.  `importlib.import_module` and `__import__` calls hide their targets from the walk, so `extra_modules` names those modules.

### Deploy: `Deployer.deploy_diff()`

```python
from chumicro_deploy import Deployer

deployer = Deployer(device)

def on_progress(fraction: float, message: str) -> None:
    print(f"[{fraction:3.0%}] {message}")

def on_file_deleted(device_path: str) -> None:
    print(f"  removed stale {device_path}")

result = deployer.deploy_diff(
    source,
    on_progress=on_progress,
    on_file_deleted=on_file_deleted,
)

if result.success:
    print(result.execute_output)
else:
    print(f"deploy failed, traceback:\n{result.traceback}")
```

`deploy_diff()` deletes old board files, copies the payload, runs the entry file, and returns a [`DeployResult`](#deployresult).  `clean=True`, the default, deletes every board file outside the payload except `boot.py`, `boot_out.txt`, and `_chu_kv.msgpack`.  `clean=False` matches `--no-wipe`, and `wipe=True` matches `--wipe`, as [What a deploy deletes](#what-a-deploy-deletes) describes.  `tail_seconds` matches `--tail-seconds`.

`deploy_diff()` raises transport errors as they happen, for code that handles failures itself.  The callbacks are optional.  `on_file_staged`, `on_file_deleted`, and `on_execute_line` report each staged file, each deleted file, and each output line once the transport finishes the step.

### Recover from failures: `RecoveringDeployer`

`RecoveringDeployer` wraps a `Deployer` with the failure report the `deploy` command prints.  The `prompt` argument picks its behavior:

- `prompt=None`, the default, makes one attempt.  On a transport error it prints the failure and the fix steps, then re-raises.
- `prompt=input`, or any callable that takes the prompt text and returns the reply, retries up to `max_attempts` times and asks between attempts.  A reply starting with `q`, `a`, or `e` stops and re-raises the last error.

```python
from chumicro_deploy import Deployer, RecoveringDeployer

runner = RecoveringDeployer(
    Deployer(device),
    prompt=input,           # leave out for one attempt with no prompt
    max_attempts=3,         # ignored when prompt is None
)

result = runner.deploy_diff(source)
```

A failure whose fix comes before any retry, such as a traceback or a board without Python firmware, prints once and re-raises in either mode.  A deploy that finishes with `success=False` and a `traceback` prints the traceback and the fix steps, then returns the result unchanged.  The `chumicro-deploy deploy` command builds this wrapper with `prompt=input`, or with `prompt=None` under `--non-interactive`.

`prompt` and `output` both accept any callable, so a test can feed scripted replies and a GUI can show the report:

```python
def my_prompt(text: str) -> str:
    ...  # return the next scripted reply, or ask in a dialog

def my_output(line: str) -> None:
    ...  # send the line to a log or a progress widget

runner = RecoveringDeployer(Deployer(device), prompt=my_prompt, output=my_output)
```

`classify_deploy_failure(error)` returns the `DeployFailureKind` for an exception, for an orchestrator that handles failures without `RecoveringDeployer`:

```python
from chumicro_deploy import DeployFailureKind, classify_deploy_failure

try:
    Deployer(device).deploy_diff(source)
except Exception as error:
    if classify_deploy_failure(error) is DeployFailureKind.PORT_UNAVAILABLE:
        ...
```

### Probe a board: `probe_device`

```python
from chumicro_deploy import probe_device

info = probe_device(device)
if info.implementation:
    print(f"{info.implementation.name} {info.implementation.version}")
    print(f"machine: {info.implementation.machine}")
else:
    print("the board answered without a runtime marker")
```

`DeviceInfo.implementation` holds the runtime name, version, and machine string.  `DeviceInfo.uid` holds the CPU id, read from `microcontroller.cpu.uid` on CircuitPython and `machine.unique_id()` on MicroPython.  `DeviceInfo.board_id` stays empty, so code that needs a board id reads `hardware.board_id` from the board's `devices.yml` entry.

### Find and install firmware: `resolve_firmware_url` and `flash_firmware`

```python
from chumicro_deploy import Device, flash_firmware, resolve_firmware_url

url = resolve_firmware_url(
    board_id="raspberry_pi_pico_w",
    runtime="circuitpython",
    version="10.1.4",
)
flash_firmware(url, Device(transport="circuitpython", address="/dev/cu.usbmodem11401"))

flash_firmware(
    "https://micropython.org/resources/firmware/LOLIN_S2_MINI-20260406-v1.28.0.bin",
    Device(transport="micropython", address="/dev/cu.usbmodem211101"),
    flash_offset="0x1000",
)
```

`resolve_firmware_url` only formats a string and makes no network request.  For `runtime="micropython"` it raises `UnresolvedFirmwareError`.  `chumicro_deploy.firmware_url.derive_firmware_url(device_entry)` finds the newest build for either runtime from a `devices.yml` entry and reads the download listings to do it.  It uses `hardware.firmware_source` when the entry sets one.  Otherwise it looks up `hardware.board_id` in the CircuitPython download bucket, or maps `hardware.machine` to a micropython.org board page.  `chumicro-workspace install-firmware` uses it when no `--url` is given.

`flash_firmware` takes the same choices as the command:

- `reflash_method=None` picks `"uf2"` for a `.uf2` link and `"esptool"` for a `.bin` link.  A link with neither ending, such as a signed CDN link, needs `reflash_method` set.
- `erase_flash=True`, the default, erases the whole flash on the esptool path.  `False` keeps the board's files and stored data.
- `flash_offset` defaults to `"0x0"`.  MicroPython on ESP32 and ESP32-S2 needs `"0x1000"`.
- `interactive=False` raises `FlashFirmwareError` where the default asks for the BOOT button.
- `on_progress` takes a `(fraction, message)` callback.  The command passes one that prints each step on stderr.

### Load `devices.yml`

```python
from chumicro_deploy.config.default import load_devices_yml

device = load_devices_yml("devices.yml", device_id="back-porch")
device = load_devices_yml("devices.yml", runtime="circuitpython")  # defaults.circuitpython
device = load_devices_yml("devices.yml")  # the one default, when defaults: names one runtime
```

`device_id` and `runtime` are mutually exclusive.  `--devices-format default` picks this loader on the command line.  Another package registers its own format through the `chumicro_deploy.config_loaders` entry-point group.

## Reference

### Failure kinds

`RecoveringDeployer` and the `deploy` command sort every transport failure into one `DeployFailureKind`.  The report prints the kind's lowercase value, such as `port_unavailable`.

| Kind | What happened | First fix | Retry offered |
|---|---|---|---|
| `PORT_UNAVAILABLE` | The serial port did not open | Plug the board in, or close the app holding the port | yes |
| `RAW_REPL_UNRESPONSIVE` | The board's REPL did not answer | Tap RESET, or leave safe mode | yes |
| `COMMAND_TIMED_OUT` | The board stopped answering mid-command, and its USB serial link stays stuck until a replug | Unplug the board and plug it back in | no |
| `NO_PYTHON_RUNTIME` | The board answers but runs other firmware, such as an Arduino sketch | Install CircuitPython or MicroPython | no |
| `CIRCUITPY_DRIVE_MISSING` | The CIRCUITPY drive is not mounted | Tap RESET, or replug the board | yes |
| `MACOS_FSKIT_WEDGED` | macOS's filesystem service is stuck, so no CIRCUITPY drive can mount | Run the command in [macOS FSKit wedge](#macos-fskit-wedge) | yes |
| `FAT_VOLUME_CORRUPT` | The CIRCUITPY drive holds damaged directory entries that only a reformat clears | `chumicro-workspace reset-board --yes --device <id>` | no |
| `FLASH_COPY_FAILED` | Copying to the CIRCUITPY drive failed: the drive is full, read-only, or reporting I/O errors | Reformat the drive, or free space | yes |
| `BOOTSTRAP_EXEC_FAILED` | Code raised an error on the board during startup | Read the traceback and fix the source | yes |
| `INSUFFICIENT_MEMORY` | The board lacks the free RAM a ram-mode deploy needs | Deploy with `--deploy-mode flash` | no |
| `TRACEBACK_RETURNED` | The entry file ran and raised a traceback | Fix the source and deploy again | no |
| `CONFIGURATION_ERROR` | The deploy call itself is wrong, such as an entry file missing from the payload | Fix the call's arguments | no |
| `UNRESOLVED_IMPORT` | An import matches no deployed file and no board built-in | Fix the import, or add its folder to the search paths | no |
| `UNKNOWN` | No known pattern matched | Tap RESET and retry | yes |

`CHUMICRO_DEPLOY_EXTRA_BUILTINS` takes a comma-separated list of extra module names to treat as board built-ins, for an `UNRESOLVED_IMPORT` raised by a built-in the walker does not know yet.

### macOS FSKit wedge

macOS mounts FAT drives such as CIRCUITPY through a user-space FSKit extension.  When that extension fails mid-probe, most often on a small FAT12 CIRCUITPY volume, it can leave the `diskarbitrationd` service stuck.  Newly plugged CIRCUITPY drives then never appear under `/Volumes`.

`RecoveringDeployer` checks for this on every `CIRCUITPY_DRIVE_MISSING` failure.  `detect_fskit_wedge()` reports whether the service is stuck.  A stuck service turns the failure into `MACOS_FSKIT_WEDGED`, whose fix steps carry this recovery command:

```
sudo killall -9 com.apple.fskit.msdos fskit_helper fskitd fskit_agent diskarbitrationd DiskArbitrationAgent
```

Run it once per wedge.  A second run kills the services again while they remount the drives.  The drives then need a physical replug.  Each killed service restarts clean under launchd, the drives mount, and Enter at the retry prompt continues the deploy.  A reboot clears a wedge the command leaves behind.

After the command, the drives work at `/Volumes` but can be missing from Finder's Locations sidebar.  Shift+Cmd+C opens the Computer view, which lists them.  A reboot restores the sidebar.

`detect_fskit_wedge()` returns `False` at once on Linux and Windows.  It also returns `False` when its own check fails, so it never blocks a real `CIRCUITPY_DRIVE_MISSING` retry.

### How each mode deploys

| Runtime | `ram` | `flash` |
|---|---|---|
| MicroPython | `mpremote mount` stages a host folder, mounts it at `/remote` on the board, and runs from there | `mpremote` copies the files to the board's flash, then runs the entry file |
| CircuitPython | The raw REPL loads each `.py` file into `sys.modules`, then runs the entry file as `__main__`.  No CIRCUITPY drive is needed | `rsync` writes the files to the CIRCUITPY drive, then the board soft-reboots and the tool captures its output |

The MicroPython transport puts `/lib` at the front of `sys.path` before it runs the entry file, or `/remote` and `/remote/lib` in ram mode.  `from my_module import thing` then finds a deployed module the same way on both runtimes.

Autoreload would restart a CircuitPython board partway through the copy, so the CircuitPython transport turns it off for the copy.  With autoreload off, the board keeps its old view of the filesystem in memory.  The transport then soft-reboots the board with Ctrl-B and Ctrl-D, and the board reads the new files.  The `code.py output:` and `Code done running.` markers CircuitPython prints separate your output from the boot banner.

A library whose `pyproject.toml` sets `requires_flash = true` under `[tool.chumicro]` declares that it runs out of memory in ram mode on small boards.  An `ImportGraphSource` deploy that reaches such a library switches to flash mode.

### Deploy steps and progress

`deploy_diff()` runs these steps in order:

1. `Device.create_transport()` builds the transport, and `connect()` opens the port.  Progress `0.0`, `connecting`.
2. `list_files_in_scope()` lists the board files the deploy may delete.  Progress `0.1`, `listing in-scope`.  `wipe=True` runs `wipe_filesystem()` here instead, and reports `wiping filesystem`.
3. `delete_files()` removes the files outside the payload.  Progress `0.2`, `cleaning stale (N)`, only when something is deleted.
4. `deploy_files()` copies the payload and runs the entry file.  Progress `0.3`, `staging`, then `0.9`, `executing`.
5. `disconnect()` closes the port, also when an earlier step raised.  Progress `1.0`, `done`.

A ram deploy lists no files in step 2, so it deletes nothing.

### `DeployResult`

| Field | Holds |
|---|---|
| `success: bool` | `True` when the board's output holds no traceback |
| `staged_files: list[str]` | The board paths the deploy wrote, sorted |
| `execute_output: str` | Everything the board printed |
| `traceback: str \| None` | The last traceback in `execute_output`, or `None` |

### Command errors and exit status

`chumicro-deploy` exits 0 on success and 1 on a failed step or a traceback from the board.  It prints `error: <message>` on stderr for a transport error, a firmware error, a `devices.yml` error, a missing file, or a bad argument value.  A wrong combination of flags, such as both `--directory` and `--file-map`, exits 2.  Any other exception prints a Python traceback.  Such a traceback is a bug worth [reporting](https://github.com/ChuMicro/ChuMicro/issues).

### Host requirements

`chumicro-deploy` runs on macOS and Linux.  Two checks fail before the serial port opens:

- **`WindowsNotSupportedError`** comes from `Deployer()` and `probe_device` on native Windows.  WSL2 with the board's USB device passed through works.
- **`RsyncMissingError`** comes before a CircuitPython flash deploy when `rsync` is missing from `PATH`.  The message carries the install command for the host's package manager.

Both import from `chumicro_deploy` and from `chumicro_deploy.host_platform`.

### Examples

These scripts run against a plugged-in board:

- [`programmatic_deploy.py`](https://github.com/ChuMicro/ChuMicro/blob/main/workbench/deploy/examples/programmatic_deploy.py) sends a folder with `DirectorySource`.
- [`file_map_deploy.py`](https://github.com/ChuMicro/ChuMicro/blob/main/workbench/deploy/examples/file_map_deploy.py) sends a multi-file payload built in memory with `FileMapSource`.
- [`import_graph_deploy.py`](https://github.com/ChuMicro/ChuMicro/blob/main/workbench/deploy/examples/import_graph_deploy.py) sends only the modules the entry file imports, with `ImportGraphSource`.
- [`demo_recovery_hand_holding.py`](https://github.com/ChuMicro/ChuMicro/blob/main/workbench/deploy/examples/demo_recovery_hand_holding.py) walks each `devices.yml` board through the failures above and prints the live report: a clean deploy, a traceback on the board, an unplugged cable, an ejected drive, an oversized payload, and a bootloader reset.

---

<div class="chumicro-footer" markdown>

[← Home](index.md)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/workbench/deploy) · \
[PyPI](https://pypi.org/project/chumicro-deploy/) · \
[Issues](https://github.com/ChuMicro/ChuMicro/issues)

</div>
