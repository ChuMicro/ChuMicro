# User Guide

This guide walks through everything `chumicro-deploy` offers today — from the `Device` struct to `Deployer.deploy()`, file sources, probing, firmware URL resolution, and end-to-end firmware flashing with `flash_firmware`. The interactive recovery layer (`InteractiveDeployer`) classifies transport failures and coaches the user through retry loops for unplug / ejected-drive / REPL-stuck failures.

## Install

```bash
pip install chumicro-deploy
```

Host-only. No bundle registration or device-side install needed. After install, a `chumicro-deploy` console script is on your PATH — see the [CLI section](#command-line-interface) at the end for the quick-invocation shortcuts.

## Command-line interface

Every Python API has a matching CLI subcommand so you don't need to write a script for one-off flashes, probes, or URL lookups.

```bash
# Probe a connected board.
chumicro-deploy probe --transport micropython --address /dev/cu.usbmodem213101

# Look up a firmware URL.
chumicro-deploy resolve-firmware-url \
    --board-id raspberry_pi_pico_w --runtime circuitpython --version 10.1.4

# Flash a Pi Pico W (UF2 path, programmatic bootloader entry).
chumicro-deploy flash \
    --transport circuitpython --address /dev/cu.usbmodem11401 \
    --url https://downloads.circuitpython.org/bin/raspberry_pi_pico_w/en_US/adafruit-circuitpython-raspberry_pi_pico_w-en_US-10.1.4.uf2 \
    --method uf2

# Flash a Lolin S2 Mini running MicroPython (esptool, erase, offset 0x1000).
chumicro-deploy flash \
    --transport micropython --address /dev/cu.usbmodem211101 \
    --url https://micropython.org/resources/firmware/LOLIN_S2_MINI-20260406-v1.28.0.bin \
    --method esptool --erase --offset 0x1000

# Deploy a directory of Python files and run the entrypoint.
chumicro-deploy deploy \
    --transport circuitpython --address /dev/cu.usbmodem11401 \
    --deploy-mode flash --drive "/Volumes/CIRCUITPY" \
    --directory ./my_app --entrypoint /code.py
```

All subcommands accept `--help` for their full option list. `chumicro-deploy flash` supports `--non-interactive` for automated flows that don't have stdin.

Every CLI command also accepts `--devices-file devices.yml --device <id>` instead of `--transport` + `--address`, so a workspace with one source-of-truth `devices.yml` doesn't repeat the same connection details everywhere:

```bash
chumicro-deploy probe --devices-file devices.yml --device back-porch
chumicro-deploy deploy --devices-file devices.yml --device back-porch \
    --directory ./my_app --entrypoint /code.py
```

When `defaults:` in the file pins a single runtime, omitting `--device` lets the loader pick that default. The schema is documented in [Decision 0027](https://github.com/ChuMicro/ChuMicro/blob/main/plans/decisions/0027-device-testing-infrastructure.md) and lives at [`chumicro_deploy.config.default.load_devices_yml`](api.md#devices-yml-schema-and-loader-registry).

### Programmatic devices.yml

The same loader is exposed as a Python function so scripts and template repos don't have to shell out:

```python
from chumicro_deploy.config.default import load_devices_yml

# Specific entry by id.
device = load_devices_yml("devices.yml", device_id="back-porch")

# Workspace's CircuitPython default — useful when devices.yml has both
# defaults.circuitpython and defaults.micropython set.
device = load_devices_yml("devices.yml", runtime="circuitpython")

# Single-runtime workspaces — neither flag needed; loader picks the
# only configured default.
device = load_devices_yml("devices.yml")
```

`device_id` and `runtime` are mutually exclusive — pass one or neither, never both.  The same shape ships as a CLI loader (`--devices-format default`), and third parties register their own config formats via the `chumicro_deploy.config_loaders` entry-point group.

## Configure a target — `Device`

A `Device` bundles the identity and connection details of one board. It is a frozen dataclass — you construct it explicitly and hand it to the deployer.

```python
from chumicro_deploy import Device

device = Device(
    transport="micropython",          # or "circuitpython"
    address="/dev/cu.usbmodem14101",  # serial port path
    baudrate=115200,                  # CircuitPython only (MP uses mpremote defaults)
    deploy_mode="ram",                # "ram" or "flash"
    circuitpy_drive_path=None,        # Path to CIRCUITPY mount for flash mode; auto-detected if omitted
    entrypoint_name=None,             # runtime default: code.py on CP, main.py on MP
    resource_prefix="/lib",           # on-device dir for non-entrypoint files
)
```

Validation runs in `__post_init__`:

- `transport` must be `"circuitpython"` or `"micropython"`.
- `deploy_mode` must be `"ram"` or `"flash"`.

### Deploy modes

| Runtime | `"ram"` | `"flash"` |
|---|---|---|
| MicroPython | mpremote `mount` — stages host dir, mounts at `/remote` on device, runs from the mount | mpremote `copy` — copies to device flash, then execs |
| CircuitPython | inline raw-REPL exec — every `.py` in *files* is injected into `sys.modules` via the class-as-module pattern, then the entrypoint runs as `__main__` | write to CIRCUITPY drive, soft-reboot, capture output |

`Deployer.deploy()` supports both modes on both runtimes. CP RAM mode does not require a mounted CIRCUITPY drive — it deploys purely over the serial raw REPL, which makes it the fastest option for a dev loop where the board is reachable over USB but you do not want to wait for the flash round-trip. The tradeoff is that RAM mode cannot ship non-`.py` assets (TOML config, JSON data, images) because it has no device filesystem to write to — use flash mode if the payload needs those.

## Pick a `FileSource`

`FileSource` is a [Protocol](https://typing.python.org/en/latest/library/typing.html#typing.Protocol) — anything that implements `.files() -> dict[str, bytes]` and `.entrypoint() -> str` works. Three built-ins cover the common cases.

### `FileMapSource` — in-memory dict

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

Values can be `str` (encoded as UTF-8) or raw `bytes`. The `entrypoint` must be a key in the dict.

### `DirectorySource` — ship a directory tree

```python
from pathlib import Path
from chumicro_deploy import DirectorySource

source = DirectorySource(
    Path("my_app"),
    entrypoint="/main.py",
    resource_prefix="/",          # default
    excluded_names=None,          # defaults: __pycache__, .DS_Store, .git, .pytest_cache, .mypy_cache
)
```

The entrypoint is the on-device path — e.g. `/main.py` means your `my_app/main.py` will land at `/main.py` on the board.

### `ImportGraphSource` — walk Python imports

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

AST walks the entrypoint, resolves each static `import` / `from ... import` against `search_paths`, and ships only the modules that resolve. Modules that cannot be resolved are silently skipped — they're assumed to be device built-ins (`gc`, `time`, `board`, etc.).

Dynamic imports (`importlib.import_module`, `__import__`) are invisible to AST walking. Pass those names explicitly via `extra_modules`.

### Bring your own

Any object satisfying the `FileSource` protocol works. `isinstance(your_source, FileSource)` returns `True` as long as `.files()` and `.entrypoint()` are defined — it's a `@runtime_checkable` Protocol, no inheritance required.

## Deploy — `Deployer.deploy()`

```python
from chumicro_deploy import Deployer

deployer = Deployer(device)

def on_progress(fraction: float, message: str) -> None:
    print(f"[{fraction:3.0%}] {message}")

def on_file_staged(device_path: str) -> None:
    print(f"  staged {device_path}")

def on_execute_line(line: str) -> None:
    print(f"  > {line}")

result = deployer.deploy(
    source,
    on_progress=on_progress,
    on_file_staged=on_file_staged,
    on_execute_line=on_execute_line,
)

if result.success:
    print("deploy ok")
    print(result.execute_output)
else:
    print(f"deploy failed — traceback:\n{result.traceback}")
```

The lifecycle is always `create_transport() -> connect() -> transport.deploy_files() -> disconnect()`. The transport is released even when `deploy_files()` raises.

`DeployResult`:

- `success: bool` — `True` when no traceback was detected in execute output.
- `staged_files: list[str]` — the on-device paths that were written (sorted).
- `execute_output: str` — combined stdout captured from the board.
- `traceback: str | None` — the last traceback block extracted from `execute_output`, or `None`.

Callbacks are all optional. `on_progress` emits coarse milestones (0.0 connecting, 0.1 collecting, 0.2 staging, 0.9 executing, 1.0 done). `on_file_staged` and `on_execute_line` are forwarded to the transport; the real transports emit them after the fact rather than live-streaming.

## Recover from deploy failures — `InteractiveDeployer`

`Deployer.deploy()` raises transport errors directly — it's the deterministic programmatic surface that automation pipelines depend on.  For interactive use (the CLI, a human invocation), `InteractiveDeployer` wraps a `Deployer` with classification, retry-loop, and user-facing coaching on failure.

```python
from chumicro_deploy import Deployer, InteractiveDeployer

interactive = InteractiveDeployer(
    Deployer(device),
    max_attempts=3,         # retry ceiling per deploy() call
)

result = interactive.deploy(source)
```

When the underlying `Deployer.deploy()` raises a `CircuitpythonTransportError` or `MicropythonTransportError`, the interactive deployer:

1. Classifies the error into a `DeployFailureKind` — one of `PORT_UNAVAILABLE`, `RAW_REPL_UNRESPONSIVE`, `CIRCUITPY_DRIVE_MISSING`, `MACOS_FSKIT_WEDGED`, `FLASH_COPY_FAILED`, `BOOTSTRAP_EXEC_FAILED`, `INSUFFICIENT_MEMORY`, `TRACEBACK_RETURNED`, `CONFIGURATION_ERROR`, or `UNKNOWN`.
2. Prints a headline, the underlying error, and the canned `RecoveryPlan` for that kind (the physical actions that typically fix it — close the app holding the port, tap RESET, replug USB, switch to flash mode, etc.).
3. Prompts the user to fix the condition and press Enter to retry, up to `max_attempts` times.  Typing `q` / `quit` / `abort` / `exit` at the prompt stops retrying and re-raises the last error.
4. For non-retryable kinds (`INSUFFICIENT_MEMORY`, `CONFIGURATION_ERROR`, `TRACEBACK_RETURNED`) it prints the coaching once and returns / re-raises without prompting — a source-level bug can't be fixed by replugging, and a too-small board can't grow more RAM by retrying.

When `Deployer.deploy()` returns a `DeployResult` with `success=False` and a `traceback`, `InteractiveDeployer` prints the traceback and a source-fix recovery plan, then returns the unchanged result.

### Plug in your own prompt and output

Both are injectable for testing and for embedding in a non-stdin environment:

```python
from collections.abc import Callable

def my_prompt(text: str) -> str:
    # e.g. feed from a scripted queue in a test, or a TUI dialog.
    ...

def my_output(line: str) -> None:
    # e.g. push to a logging framework or a progress widget.
    ...

interactive = InteractiveDeployer(
    Deployer(device),
    prompt=my_prompt,
    output=my_output,
)
```

### Classify errors directly

`classify_deploy_failure(exception)` is exported so you can build your own orchestrator without using `InteractiveDeployer`:

```python
from chumicro_deploy import DeployFailureKind, classify_deploy_failure

try:
    Deployer(device).deploy(source)
except Exception as error:
    kind = classify_deploy_failure(error)
    if kind is DeployFailureKind.PORT_UNAVAILABLE:
        ...
```

### macOS FSKit / DiskArbitration wedge

Recent macOS releases replaced the in-kernel `msdosfs` driver with a user-space FSKit extension.  When that extension errors out mid-probe — most often on a small CIRCUITPY FAT12 volume — it can leave `diskarbitrationd` stuck in an uninterruptible kernel wait, and newly inserted CIRCUITPY drives never appear under `/Volumes`.

`InteractiveDeployer` auto-detects this condition.  On a `CIRCUITPY_DRIVE_MISSING` failure it calls `detect_fskit_wedge()` (from `chumicro_deploy.macos_fskit`); if the daemon is wedged, it promotes the kind to `MACOS_FSKIT_WEDGED` and prints a coaching block with the exact recovery command:

```
sudo killall -9 com.apple.fskit.msdos fskit_helper fskitd fskit_agent diskarbitrationd && launchctl kickstart -k gui/$(id -u)/com.apple.DiskArbitrationAgent
```

The system daemons respawn via launchd; the `launchctl kickstart -k` bounces the per-user agent (which doesn't auto-respawn).  After the paste, CIRCUITPY drives mount and `chumicro-deploy` can proceed — hit Enter at the retry prompt to continue.

Heads-up: on recent macOS the drives may be fully functional (mounted at `/Volumes`, readable, writable, deployable) but *not* appear in Finder's Locations sidebar.  That's an Apple FSKit-Finder regression unrelated to the deploy — reach them via Shift+Cmd+C (Computer view) or drag one into the Favorites sidebar section.  A reboot clears it.

Detection is non-darwin-safe (returns `False` immediately on Linux / Windows) and fails open on any subprocess error, so it never blocks a legitimate `CIRCUITPY_DRIVE_MISSING` retry.

### Try it against real boards

[`workbench/deploy/examples/demo_recovery_hand_holding.py`](https://github.com/ChuMicro/ChuMicro/blob/main/workbench/deploy/examples/demo_recovery_hand_holding.py) walks every configured `devices.yml` board through each failure scenario and prints the coaching output live.  Scenarios today: happy-path baseline, traceback-on-board, physical unplug (`PORT_UNAVAILABLE`), drive-ejected (`CIRCUITPY_DRIVE_MISSING`, with `MACOS_FSKIT_WEDGED` promotion when the wedge is live), oversized-payload (`FLASH_COPY_FAILED`), and silent bootloader-reset verification.  Run it when you want to see what the CLI actually says to the user on a real cable-out / drive-ejected / board-rebooted failure.

## Probe a board — `probe_device`

```python
from chumicro_deploy import probe_device

info = probe_device(device)
if info.implementation:
    print(f"{info.implementation.name} {info.implementation.version}")
    print(f"machine: {info.implementation.machine}")
else:
    print("probe did not return marker — firmware may not support sys.implementation")
```

`DeviceInfo` carries `implementation` (name / version / machine), plus reserved `board_id` and `uid` fields — empty today, populated in a future slice by a richer on-device probe.

## Resolve firmware URLs — `resolve_firmware_url`

```python
from chumicro_deploy import resolve_firmware_url

cp_url = resolve_firmware_url(
    board_id="raspberry_pi_pico_w",
    runtime="circuitpython",
    version="10.1.4",
)
# https://downloads.circuitpython.org/bin/raspberry_pi_pico_w/en_US/adafruit-circuitpython-raspberry_pi_pico_w-en_US-10.1.4.uf2
```

MicroPython URLs embed a per-build date that cannot be inferred from the version alone. Calling with `runtime="micropython"` raises `UnresolvedFirmwareError` with a clear roadmap message until live listing lookup lands in a later slice; for now, supply the URL yourself.

## Flash firmware — `flash_firmware`

`flash_firmware` downloads a firmware image and writes it to a connected board.  Destructive: overwrites whatever firmware is currently installed.  Two reflash backends:

- **`uf2`** — for RP2040 / RP2350 (Pi Pico family) and any board shipping TinyUF2.  Uses the UF2 bootloader drive; requires a `.uf2` URL.  Programmatic bootloader entry works on CircuitPython and on MicroPython ports that implement `machine.bootloader()`.
- **`esptool`** — for the ESP32 family (ESP32, S2, S3, C3, C6) regardless of runtime.  Shells out to `esptool` over serial; requires a `.bin` URL.

```python
from chumicro_deploy import Device, flash_firmware, resolve_firmware_url

device = Device(
    transport="circuitpython",
    address="/dev/cu.usbmodem11401",
)

# UF2 path — Pi Pico W to a specific CircuitPython build.
url = resolve_firmware_url(
    board_id="raspberry_pi_pico_w",
    runtime="circuitpython",
    version="10.1.4",
)
flash_firmware(url, device, reflash_method="uf2")

# esptool path — Lolin S2 Mini with MicroPython, erase first, offset 0x1000.
flash_firmware(
    "https://micropython.org/resources/firmware/LOLIN_S2_MINI-20260406-v1.28.0.bin",
    Device(transport="micropython", address="/dev/cu.usbmodem211101"),
    reflash_method="esptool",
    erase_flash=True,
    flash_offset="0x1000",
)
```

**Method selection notes:**

- CircuitPython `.bin` images use offset `"0x0"` (the default).  MicroPython ESP32 / S2 / S3 `.bin` images need `"0x1000"`.  Using the wrong offset bricks the bootloader region and requires a manual BOOT + RESET hold to recover — `chumicro-deploy` cannot auto-detect which ecosystem a `.bin` came from.
- Pass `interactive=False` in automated flows without stdin.  When programmatic bootloader entry fails, the default is to prompt the user to hold BOOTSEL / GPIO0; `interactive=False` raises `FlashFirmwareError` instead.
- `erase_flash=True` wipes every user partition (CIRCUITPY drive, stored WiFi credentials, NVS).  Recommended for first-install and recovery workflows; default `False` preserves user data on ordinary upgrades.
- `on_progress` takes an optional `(fraction, message)` callback for UI integration — the CLI wires it to a stderr progress line.

## Interactive recovery — `InteractiveDeployer`

`InteractiveDeployer` wraps a `Deployer` with a classify-and-coach retry loop.  On a `CircuitpythonTransportError` or `MicropythonTransportError`, it routes the failure through `classify_deploy_failure`, prints the matching `RecoveryPlan` (headline + ordered fix-steps), and — when the plan is retryable — prompts the user to fix the condition and press Enter to retry.  After `max_attempts` attempts the last exception re-raises.

```python
from chumicro_deploy import Deployer, InteractiveDeployer

deployer = InteractiveDeployer(Deployer(device), max_attempts=3)
result = deployer.deploy(source)
```

Use it from the CLI or any interactive tool where a human is present and can unplug, tap RESET, or close a conflicting app; stick with the plain `Deployer` for scripts where retries would just confuse the output.

On macOS, the `CIRCUITPY_DRIVE_MISSING` kind auto-promotes to `MACOS_FSKIT_WEDGED` when `detect_fskit_wedge()` confirms the FSKit / DiskArbitration daemons are stuck — the recovery block then prints the exact `sudo killall … && launchctl kickstart …` command to unstick them.

## Tail the board with chumicro-repl

`Deployer.deploy()` returns once the entrypoint executes; if the entrypoint then enters a long-running loop (a heartbeat, a sensor publisher, a server) the deploy is "done" but the interesting output is just starting.  [`chumicro-repl`](https://github.com/ChuMicro/ChuMicro/tree/main/workbench/repl) is the sister workbench tool for this — it streams the friendly REPL with traceback highlighting and exposes a `tail()` follow-mode that fails fast on a crash:

```python
from chumicro_deploy import Deployer
from chumicro_repl import tail, ExitCode

result = Deployer(device).deploy(source)
if not result.success:
    raise SystemExit(f"deploy failed:\n{result.traceback}")

# Watch for ten seconds, return non-zero if the board crashes.
follow = tail(device, seconds=10.0, fail_on_traceback=True)
if follow is ExitCode.TRACEBACK_DETECTED:
    raise SystemExit("board crashed during follow-up tail")
```

`chumicro-repl` reuses the same `Device` object, the same `devices.yml` schema, and the same pyserial transport, so a deploy → tail pipeline never repeats connection details.  For interactive use, `chumicro-repl --devices-file devices.yml --device <id>` opens a TUI matching `mpremote repl` keybindings; for headless tests, `ReplSession(device)` exposes `exec(code)` / `call(function_name, *args, **kwargs)` / `read_until(pattern, timeout)` over raw REPL.

## Host platform requirements

`chumicro-deploy` runs on macOS and Linux today.  Two host prerequisites are surfaced as explicit exceptions when missing, so failures land before the serial port opens:

- **`WindowsNotSupportedError`** — raised from `Deployer.__init__` and `probe_device` when `sys.platform == "win32"`.  Windows support is tracked but not implemented; on Windows, run `chumicro-deploy` from WSL2 against a USB-passed-through device.
- **`RsyncMissingError`** — raised before flash-mode CircuitPython deploy when `rsync` is not on `$PATH`.  CIRCUITPY drive synchronization needs `rsync` for atomic, deterministic file updates; the error message includes a package-manager-specific install hint (`brew install rsync` / `apt install rsync` / `dnf install rsync`) so the fix is one line away.

Both errors live in `chumicro_deploy.host_platform` and are re-exported at the package top level.

## Runtime notes

### MicroPython `sys.path`

MicroPython does not include `/lib` on `sys.path` by default (CircuitPython does). `MicropythonTransport.deploy_files` auto-inserts `/lib` (copy mode) or `/remote/lib` (mount mode) into `sys.path` before executing the entrypoint. This keeps `from my_module import ...` working consistently across both runtimes without per-runtime boilerplate in your code.

### CircuitPython flash-mode soft-reboot

CircuitPython caches the FAT32 filesystem view in-memory. Writing to the CIRCUITPY drive while autoreload is disabled would leave the board reading stale content. `CircuitpythonTransport.deploy_files` disables autoreload during writes (to prevent mid-deploy resets), then manually soft-reboots the board via Ctrl-B + Ctrl-D. The board picks up the new files on the fresh boot; the `code.py output:` / `Code done running.` markers CP emits are used to extract your entrypoint's output from the boot banner.

If your entrypoint is an infinite loop (no `return`), `deploy_files` times out at the transport's `timeout` (default 10 s) and returns whatever was captured up to that point.

## See also

- [API Reference](api.md)
- [Source](https://github.com/ChuMicro/ChuMicro/tree/main/workbench/deploy)
- [Decision 0032](https://github.com/ChuMicro/ChuMicro/blob/main/plans/decisions/0032-workbench-host-tools.md) — why this package lives in `workbench/` rather than `libraries/`.
- [Decision 0027](https://github.com/ChuMicro/ChuMicro/blob/main/plans/decisions/0027-device-testing-infrastructure.md) — transport protocol origin.
- [Decision 0028](https://github.com/ChuMicro/ChuMicro/blob/main/plans/decisions/0028-deploy-modes.md) — deploy-mode semantics per runtime.
