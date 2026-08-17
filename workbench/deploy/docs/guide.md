# User Guide

`chumicro-deploy` writes Python code onto CircuitPython and MicroPython boards from your laptop, then helps you recover when something goes wrong.

This guide covers `Device`, `Deployer.deploy_diff()`, the three file sources, probing, firmware URL resolution, and end-to-end flashing with `flash_firmware`.  It ends with `RecoveringDeployer`, the wrapper that names the transport failure you hit (unplugged cable, ejected drive, stuck REPL) and walks you through a retry.

## Install

```bash
pip install chumicro-deploy
```

Host-only. No bundle registration or device-side install needed. After install, a `chumicro-deploy` console script is on your PATH. See the [CLI section](#command-line-interface) at the end for the quick-invocation shortcuts.

## Command-line interface

Four subcommands cover the one-off jobs you'd otherwise write a script for: `probe`, `deploy`, `flash-firmware`, and `resolve-firmware-url`.

```bash
# Probe a connected board.
chumicro-deploy probe --transport micropython --address /dev/cu.usbmodem213101

# Look up a firmware URL.
chumicro-deploy resolve-firmware-url \
    --board-id raspberry_pi_pico_w --runtime circuitpython --version 10.1.4

# Flash a Pi Pico W (UF2 path, programmatic bootloader entry).
# --method is inferred from the .uf2 extension.
chumicro-deploy flash-firmware \
    --transport circuitpython --address /dev/cu.usbmodem11401 \
    --url https://downloads.circuitpython.org/bin/raspberry_pi_pico_w/en_US/adafruit-circuitpython-raspberry_pi_pico_w-en_US-10.1.4.uf2

# Flash a Lolin S2 Mini running MicroPython (esptool path, offset 0x1000).
# --method is inferred from the .bin extension.  erase-flash runs by
# default; pass --no-erase to preserve user data on an in-place upgrade.
chumicro-deploy flash-firmware \
    --transport micropython --address /dev/cu.usbmodem211101 \
    --url https://micropython.org/resources/firmware/LOLIN_S2_MINI-20260406-v1.28.0.bin \
    --offset 0x1000

# Deploy a directory of Python files and run the entrypoint.
chumicro-deploy deploy \
    --transport circuitpython --address /dev/cu.usbmodem11401 \
    --deploy-mode flash \
    --directory ./my_app --entrypoint /code.py
```

All subcommands accept `--help` for their full option list. Both `chumicro-deploy deploy` and `chumicro-deploy flash-firmware` support `--non-interactive`.  Without that flag, `deploy` wraps every run in `RecoveringDeployer` with `prompt=input` (see [Recover from deploy failures](#recover-from-deploy-failures-recoveringdeployer) below) so transport failures are classified and coached instead of producing a raw traceback.  Pass `--non-interactive` from CI / scripted flows that don't have stdin to answer retry prompts.  That builds the same wrapper with `prompt=None`, which reports once and re-raises.

`main()` catches the documented exception types (transport errors, `FlashFirmwareError`, `UnresolvedFirmwareError`, `DeviceConfigError`, `FileNotFoundError`, `ValueError`) and prints `error: <message>` on stderr with exit code 1.  Anything else propagates as a Python traceback; those are bugs, not user-facing failures.

The three board-facing subcommands (`probe`, `deploy`, `flash-firmware`) also accept `--devices-file devices.yml --device <id>` instead of `--transport` + `--address`, so a workspace with one source-of-truth `devices.yml` doesn't repeat the same connection details everywhere.  `resolve-firmware-url` needs no board, so it takes neither:

```bash
chumicro-deploy probe --devices-file devices.yml --device back-porch
chumicro-deploy deploy --devices-file devices.yml --device back-porch \
    --directory ./my_app --entrypoint /code.py
```

When `defaults:` in the file pins a single runtime, omitting `--device` lets the loader pick that default. The schema lives at [`chumicro_deploy.config.default.load_devices_yml`](api.md#devicesyml-schema-and-loader-registry).

### Programmatic devices.yml

The same loader is exposed as a Python function so scripts and template repos don't have to shell out:

```python
from chumicro_deploy.config.default import load_devices_yml

# Specific entry by id.
device = load_devices_yml("devices.yml", device_id="back-porch")

# Workspace's CircuitPython default, useful when devices.yml has both
# defaults.circuitpython and defaults.micropython set.
device = load_devices_yml("devices.yml", runtime="circuitpython")

# Single-runtime workspaces need neither flag; the loader picks the
# only configured default.
device = load_devices_yml("devices.yml")
```

`device_id` and `runtime` are mutually exclusive: pass one or neither, never both.  The same shape ships as a CLI loader (`--devices-format default`), and third parties register their own config formats via the `chumicro_deploy.config_loaders` entry-point group.

## Configure a target: `Device`

A `Device` bundles the identity and connection details of one board. It is a frozen dataclass: you construct it explicitly and hand it to the deployer.

```python
from chumicro_deploy import Device

device = Device(
    transport="micropython",          # or "circuitpython"
    address="/dev/cu.usbmodem14101",  # serial port path
    baudrate=115200,                  # CircuitPython only (MP uses mpremote defaults)
    deploy_mode="ram",                # "ram" or "flash"
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
| MicroPython | mpremote `mount`: stages host dir, mounts at `/remote` on device, runs from the mount | mpremote `copy`: copies to device flash, then execs |
| CircuitPython | inline raw-REPL exec: every `.py` in *files* is injected into `sys.modules` via the class-as-module pattern, then the entrypoint runs as `__main__` | write to CIRCUITPY drive, soft-reboot, capture output |

`Deployer.deploy_diff()` supports both modes on both runtimes. CP RAM mode does not require a mounted CIRCUITPY drive, since it deploys purely over the serial raw REPL. That makes it the fastest option for a dev loop where the board is reachable over USB but you do not want to wait for the flash round-trip. The tradeoff is that RAM mode cannot ship non-`.py` assets (TOML config, JSON data, images), because it has no device filesystem to write to. Use flash mode if the payload needs those.

## Pick a `FileSource`

`FileSource` is a [Protocol](https://typing.python.org/en/latest/library/typing.html#typing.Protocol): anything that implements `.files() -> dict[str, bytes]` and `.entrypoint() -> str` works. Three built-ins cover the common cases.

### `FileMapSource`: in-memory dict

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

### `DirectorySource`: ship a directory tree

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

The entrypoint is the on-device path. `/main.py` means your `my_app/main.py` will land at `/main.py` on the board.

### `ImportGraphSource`: walk Python imports

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

AST walks the entrypoint, resolves each static `import` / `from ... import` against `search_paths`, and ships only the modules that resolve.

An import that resolves to nothing is not skipped quietly. Names on the device-built-in allowlist (`gc`, `time`, `board`, and the rest of `chumicro_deploy.import_allowlist.DEVICE_BUILTIN_MODULES`) are dropped, because the board supplies them. Any other unresolved import raises `UnresolvedImportError` from the constructor, naming the file that imports it, so a typo or a missing search path fails on your laptop instead of as an `ImportError` on the board. An import guarded by `try` / `except ImportError` counts as optional and never refuses the deploy.

Dynamic imports (`importlib.import_module`, `__import__`) are invisible to AST walking. Pass those names explicitly via `extra_modules`.

### Bring your own

Any object satisfying the `FileSource` protocol works. `isinstance(your_source, FileSource)` returns `True` as long as `.files()` and `.entrypoint()` are defined. It's a `@runtime_checkable` Protocol, so no inheritance is required.

## Deploy: `Deployer.deploy_diff()`

```python
from chumicro_deploy import Deployer

deployer = Deployer(device)

def on_progress(fraction: float, message: str) -> None:
    print(f"[{fraction:3.0%}] {message}")

def on_file_staged(device_path: str) -> None:
    print(f"  staged {device_path}")

def on_file_deleted(device_path: str) -> None:
    print(f"  removed stale {device_path}")

def on_execute_line(line: str) -> None:
    print(f"  > {line}")

result = deployer.deploy_diff(
    source,
    on_progress=on_progress,
    on_file_staged=on_file_staged,
    on_file_deleted=on_file_deleted,
    on_execute_line=on_execute_line,
)

if result.success:
    print("deploy ok")
    print(result.execute_output)
else:
    print(f"deploy failed, traceback:\n{result.traceback}")
```

`deploy_diff()` is the one stage primitive: it lists the on-device files in scope, deletes the stale set (anything not in the new payload), then stages and runs the entrypoint. It is **clean-slate by default** (`clean=True`): the board is reconciled to exactly the payload plus the closed device keep set (`boot.py`, `boot_out.txt`, `_chu_kv.msgpack`), and a board-resident `settings.toml` is evicted. Pass `clean=False` for the additive opt-out (reconcile only the entrypoint/state files + `/lib`, leave other board files), or `wipe=True` for a full filesystem erase (keep set included) before staging.

The lifecycle is `create_transport() -> connect() -> list_files_in_scope() -> delete_files(stale) -> transport.deploy_files() -> disconnect()` (a RAM-mode deploy lists nothing and collapses to a plain stage; a `wipe=True` deploy replaces the list/delete step with `wipe_filesystem()`). The transport is released even when `deploy_files()` raises.

`DeployResult`:

- `success: bool` is `True` when no traceback was detected in the execute output.
- `staged_files: list[str]` holds the on-device paths that were written, sorted.
- `execute_output: str` is the combined stdout captured from the board.
- `traceback: str | None` is the last traceback block extracted from `execute_output`, or `None`.

Callbacks are all optional. `on_progress` emits coarse milestones (0.0 connecting, 0.1 listing in-scope, 0.2 cleaning stale (only when there is a stale set), 0.3 staging, 0.9 executing, 1.0 done). `on_file_staged`, `on_file_deleted`, and `on_execute_line` are forwarded to the transport / diff step; the real transports emit them after the fact rather than live-streaming.

## Recover from deploy failures: `RecoveringDeployer`

`Deployer.deploy_diff()` raises transport errors directly, since it's the deterministic programmatic surface that automation pipelines depend on.  For interactive use, `RecoveringDeployer` wraps a `Deployer` with classification and user-facing coaching on failure, and optionally an Enter-to-retry loop.  Two modes selected by the `prompt` argument:

- `prompt=None` (the default, for CI and scripted flows): runs once, prints the classified failure + ordered fix steps on a transport error, then re-raises.
- `prompt=input` (or any `(str) -> str` callable, for interactive flows): runs up to `max_attempts` times, asks the user between attempts.  Any reply starting with `q`, `a`, or `e` aborts.

The `chumicro-deploy deploy` CLI builds the wrapper with `prompt=input` by default; pass `--non-interactive` to switch to `prompt=None`.  `chumicro-workspace deploy` / `deploy-example` / `demo` do the same.  When you call `Deployer.deploy_diff()` from your own Python code you opt in by constructing the wrapper explicitly:

```python
from chumicro_deploy import Deployer, RecoveringDeployer

runner = RecoveringDeployer(
    Deployer(device),
    prompt=input,           # omit (default None) for one-shot non-interactive coaching
    max_attempts=3,         # retry ceiling; ignored when prompt is None
)

result = runner.deploy_diff(source)

# clean=False is the additive opt-out; wipe=True is a full erase.
result = runner.deploy_diff(source, wipe=True)
```

When the underlying `Deployer.deploy_diff()` raises a `CircuitpythonTransportError` or `MicropythonTransportError`, `RecoveringDeployer`:

1. Classifies the error into a `DeployFailureKind`: one of `PORT_UNAVAILABLE`, `RAW_REPL_UNRESPONSIVE`, `COMMAND_TIMED_OUT`, `NO_PYTHON_RUNTIME`, `CIRCUITPY_DRIVE_MISSING`, `MACOS_FSKIT_WEDGED`, `FAT_VOLUME_CORRUPT`, `FLASH_COPY_FAILED`, `BOOTSTRAP_EXEC_FAILED`, `INSUFFICIENT_MEMORY`, `TRACEBACK_RETURNED`, `CONFIGURATION_ERROR`, `UNRESOLVED_IMPORT`, or `UNKNOWN`.
2. Prints a headline, the underlying error, and the canned `RecoveryPlan` for that kind (the physical actions that typically fix it: close the app holding the port, tap RESET, replug USB, switch to flash mode).
3. With `prompt=input`: asks the user to fix the condition and press Enter to retry, up to `max_attempts` times.  Typing `q` / `quit` / `abort` / `exit` at the prompt stops retrying and re-raises the last error.  With `prompt=None`: re-raises immediately after printing.
4. For non-retryable kinds (`COMMAND_TIMED_OUT`, `NO_PYTHON_RUNTIME`, `FAT_VOLUME_CORRUPT`, `INSUFFICIENT_MEMORY`, `CONFIGURATION_ERROR`, `UNRESOLVED_IMPORT`, `TRACEBACK_RETURNED`) it prints the coaching once and re-raises without prompting, regardless of mode.  A source-level bug can't be fixed by replugging, a too-small board can't grow more RAM by retrying, and a wedged USB link, a missing Python runtime, or a corrupt CIRCUITPY filesystem each need the fix steps applied first (replug, `install-firmware`, `reset-board`) before a deploy can get anywhere.

When `Deployer.deploy_diff()` returns a `DeployResult` with `success=False` and a `traceback`, `RecoveringDeployer` prints the traceback and a source-fix recovery plan, then returns the unchanged result.

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

runner = RecoveringDeployer(
    Deployer(device),
    prompt=my_prompt,
    output=my_output,
)
```

### Classify errors directly

`classify_deploy_failure(exception)` is exported so you can build your own orchestrator without using `RecoveringDeployer`:

```python
from chumicro_deploy import DeployFailureKind, classify_deploy_failure

try:
    Deployer(device).deploy_diff(source)
except Exception as error:
    kind = classify_deploy_failure(error)
    if kind is DeployFailureKind.PORT_UNAVAILABLE:
        ...
```

### macOS FSKit / DiskArbitration wedge

Recent macOS releases replaced the in-kernel `msdosfs` driver with a user-space FSKit extension.  When that extension errors out mid-probe (most often on a small CIRCUITPY FAT12 volume), it can leave `diskarbitrationd` stuck in an uninterruptible kernel wait, and newly inserted CIRCUITPY drives never appear under `/Volumes`.

`RecoveringDeployer` auto-detects this condition.  On a `CIRCUITPY_DRIVE_MISSING` failure it calls `detect_fskit_wedge()` (from `chumicro_deploy.macos_fskit`); if the daemon is wedged, it promotes the kind to `MACOS_FSKIT_WEDGED` and prints a coaching block with the exact recovery command:

```
sudo killall -9 com.apple.fskit.msdos fskit_helper fskitd fskit_agent diskarbitrationd DiskArbitrationAgent
```

Each killed daemon respawns under launchd in a clean state.  The per-user `DiskArbitrationAgent` is killed directly rather than bounced via `launchctl kickstart`, which is SIP-blocked on modern macOS; XPC clients re-trigger its on-demand load despite `KeepAlive=false`.  After the paste, CIRCUITPY drives mount and `chumicro-deploy` can proceed.  Hit Enter at the retry prompt to continue.

Heads-up: on recent macOS the drives may be fully functional (mounted at `/Volumes`, readable, writable, deployable) but *not* appear in Finder's Locations sidebar.  That's an Apple FSKit-Finder regression unrelated to the deploy.  Reach them via Shift+Cmd+C (Computer view) or drag one into the Favorites sidebar section.  A reboot clears it.

Detection is non-darwin-safe (returns `False` immediately on Linux / Windows) and fails open on any subprocess error, so it never blocks a legitimate `CIRCUITPY_DRIVE_MISSING` retry.

### Try it against real boards

[`workbench/deploy/examples/demo_recovery_hand_holding.py`](https://github.com/ChuMicro/ChuMicro/blob/main/workbench/deploy/examples/demo_recovery_hand_holding.py) walks every configured `devices.yml` board through each failure scenario and prints the coaching output live.  Scenarios today: happy-path baseline, traceback-on-board, physical unplug (`PORT_UNAVAILABLE`), drive-ejected (`CIRCUITPY_DRIVE_MISSING`, with `MACOS_FSKIT_WEDGED` promotion when the wedge is live), oversized-payload (`FLASH_COPY_FAILED`), and silent bootloader-reset verification.  Run it when you want to see what the CLI actually says to the user on a real cable-out / drive-ejected / board-rebooted failure.

For shorter end-to-end examples that exercise each built-in `FileSource` against a plugged-in board, see also:

- [`programmatic_deploy.py`](https://github.com/ChuMicro/ChuMicro/blob/main/workbench/deploy/examples/programmatic_deploy.py): `DirectorySource` walking a local dir.
- [`file_map_deploy.py`](https://github.com/ChuMicro/ChuMicro/blob/main/workbench/deploy/examples/file_map_deploy.py): `FileMapSource` for an in-memory multi-file payload.
- [`import_graph_deploy.py`](https://github.com/ChuMicro/ChuMicro/blob/main/workbench/deploy/examples/import_graph_deploy.py): `ImportGraphSource` AST-walking from an entrypoint, shipping only reachable modules.

## Probe a board: `probe_device`

```python
from chumicro_deploy import probe_device

info = probe_device(device)
if info.implementation:
    print(f"{info.implementation.name} {info.implementation.version}")
    print(f"machine: {info.implementation.machine}")
else:
    print("probe did not return a marker; firmware may not support sys.implementation")
```

`DeviceInfo` carries `implementation` (name / version / machine) and a `uid` field filled from the same probe (`microcontroller.cpu.uid` on CircuitPython, `machine.unique_id()` on MicroPython).  Its third field, `board_id`, is an empty string: `probe_device` does not set it, so anything that needs a board ID reads it from the `devices.yml` entry's `hardware.board_id` instead.

## Resolve firmware URLs: `resolve_firmware_url`

```python
from chumicro_deploy import resolve_firmware_url

cp_url = resolve_firmware_url(
    board_id="raspberry_pi_pico_w",
    runtime="circuitpython",
    version="10.1.4",
)
# https://downloads.circuitpython.org/bin/raspberry_pi_pico_w/en_US/adafruit-circuitpython-raspberry_pi_pico_w-en_US-10.1.4.uf2
```

`resolve_firmware_url` is a pure formatter: it builds a CircuitPython URL from the board ID and version you pass, and makes no network call.  MicroPython URLs embed a per-build date that cannot be inferred from the version alone, so calling with `runtime="micropython"` raises `UnresolvedFirmwareError`.

For MicroPython, and for "give me the latest build" on either runtime, use `chumicro_deploy.firmware_url.derive_firmware_url(device_entry)`.  It takes a `devices.yml` device dict and reads the listing pages: `hardware.firmware_source` wins if set, CircuitPython entries resolve `hardware.board_id` against the Adafruit S3 bucket, and MicroPython entries map `hardware.machine` to a board name and scrape that board's micropython.org download page.  `chumicro-workspace install-firmware` uses this path when you omit `--url`.

## Flash firmware: `flash_firmware`

`flash_firmware` downloads a firmware image and writes it to a connected board.  Destructive: overwrites whatever firmware is currently installed.  Two reflash backends:

- **`uf2`** covers RP2040 / RP2350 (Pi Pico family) and any board shipping TinyUF2.  Uses the UF2 bootloader drive; requires a `.uf2` URL.  Programmatic bootloader entry works on CircuitPython and on MicroPython ports that implement `machine.bootloader()`.
- **`esptool`** covers the ESP32 family (ESP32, S2, S3, C3, C6) regardless of runtime.  Shells out to `esptool` over serial; requires a `.bin` URL.

```python
from chumicro_deploy import Device, flash_firmware, resolve_firmware_url

device = Device(
    transport="circuitpython",
    address="/dev/cu.usbmodem11401",
)

# UF2 path: Pi Pico W to a specific CircuitPython build.
# reflash_method=None (the default) infers from the .uf2 extension.
url = resolve_firmware_url(
    board_id="raspberry_pi_pico_w",
    runtime="circuitpython",
    version="10.1.4",
)
flash_firmware(url, device)

# esptool path: Lolin S2 Mini with MicroPython, offset 0x1000.
# erase_flash=True is the default; pass False to preserve user data.
flash_firmware(
    "https://micropython.org/resources/firmware/LOLIN_S2_MINI-20260406-v1.28.0.bin",
    Device(transport="micropython", address="/dev/cu.usbmodem211101"),
    flash_offset="0x1000",
)
```

**Method selection notes:**

- `reflash_method=None` (default) infers the method from the URL extension: `.uf2` → `"uf2"`, `.bin` → `"esptool"`.  Pass explicitly for URLs that don't carry an extension (e.g. signed CDN URLs with a query-string-only filename).
- CircuitPython `.bin` images use offset `"0x0"` (the default).  MicroPython ESP32 / S2 / S3 `.bin` images need `"0x1000"`.  Using the wrong offset bricks the bootloader region and requires a manual BOOT + RESET hold to recover, and `chumicro-deploy` cannot auto-detect which ecosystem a `.bin` came from.
- Pass `interactive=False` in automated flows without stdin.  When programmatic bootloader entry fails, the default is to prompt the user to hold BOOTSEL / GPIO0; `interactive=False` raises `FlashFirmwareError` instead.
- `erase_flash=True` (the default for the esptool path) wipes every user partition (CIRCUITPY drive, stored WiFi credentials, NVS) so a fresh reflash doesn't inherit leftover sectors from a previous build.  Pass `False` to preserve user data on an in-place upgrade.
- `on_progress` takes an optional `(fraction, message)` callback for UI integration; the CLI wires it to a stderr progress line.

## Tail the board with chumicro-repl

`Deployer.deploy_diff()` returns once the entrypoint executes; if the entrypoint then enters a long-running loop (a heartbeat, a sensor publisher, a server) the deploy is "done" but the interesting output is just starting.  [`chumicro-repl`](https://chumicro.github.io/ChuMicro/repl/stable/) is the sister workbench tool for this.  It streams the friendly REPL with traceback highlighting and exposes a `tail()` follow-mode that fails fast on a crash:

```python
from chumicro_deploy import Deployer
from chumicro_repl import tail, ExitCode

result = Deployer(device).deploy_diff(source)
if not result.success:
    raise SystemExit(f"deploy failed:\n{result.traceback}")

# Watch for ten seconds, return non-zero if the board crashes.
follow = tail(device, seconds=10.0, fail_on_traceback=True)
if follow is ExitCode.TRACEBACK_DETECTED:
    raise SystemExit("board crashed during follow-up tail")
```

`chumicro-repl` reuses the same `Device` object, the same `devices.yml` schema, and the same pyserial transport, so a deploy → tail pipeline never repeats connection details.

Its CLI takes a port, not a device id: `chumicro-repl --address /dev/cu.usbmodem14101`.  To open a board by the name it carries in `devices.yml`, go through the workspace CLI instead:

```bash
chumicro-workspace repl --device back-porch
```

Either way the session defaults to `--mode auto`, which picks the host-side line editor (persistent history, cursor editing, Ctrl-R reverse search) when stdin is a TTY, and byte-for-byte passthrough when stdin is piped.  Pass `--mode passthrough` explicitly for the mpremote-style behavior that raw-REPL framing and paste mode need.

For headless tests, `ReplSession(device)` exposes `exec(code)` / `call(function_name, *args, **kwargs)` / `read_until(pattern, timeout)` over raw REPL.

## Host platform requirements

`chumicro-deploy` runs on macOS and Linux today.  Two host prerequisites are surfaced as explicit exceptions when missing, so failures land before the serial port opens:

- **`WindowsNotSupportedError`** is raised from `Deployer.__init__` and `probe_device` when `sys.platform == "win32"`.  Windows is not supported; run `chumicro-deploy` from WSL2 against a USB-passed-through device instead.
- **`RsyncMissingError`** is raised before a flash-mode CircuitPython deploy when `rsync` is not on `$PATH`.  CIRCUITPY drive synchronization needs `rsync` for atomic, deterministic file updates; the error message includes a package-manager-specific install hint (`brew install rsync` / `apt install rsync` / `dnf install rsync`) so the fix is one line away.

Both errors live in `chumicro_deploy.host_platform` and are re-exported at the package top level.

## Runtime notes

### MicroPython `sys.path`

MicroPython does not include `/lib` on `sys.path` by default (CircuitPython does). `MicropythonTransport.deploy_files` auto-inserts `/lib` (copy mode) or `/remote/lib` (mount mode) into `sys.path` before executing the entrypoint. This keeps `from my_module import ...` working consistently across both runtimes without per-runtime boilerplate in your code.

### CircuitPython flash-mode soft-reboot

CircuitPython caches the FAT32 filesystem view in-memory. Writing to the CIRCUITPY drive while autoreload is disabled would leave the board reading stale content. `CircuitpythonTransport.deploy_files` disables autoreload during writes (to prevent mid-deploy resets), then manually soft-reboots the board via Ctrl-B + Ctrl-D. The board picks up the new files on the fresh boot; the `code.py output:` / `Code done running.` markers CP emits are used to extract your entrypoint's output from the boot banner.

If your entrypoint is an infinite loop (no `return`), `deploy_files` times out at the transport's `timeout` (default 10 s) and returns whatever was captured up to that point.

---

<div class="chumicro-footer" markdown>

[← Home](index.md)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/workbench/deploy) · \
[PyPI](https://pypi.org/project/chumicro-deploy/) · \
[Issues](https://github.com/ChuMicro/ChuMicro/issues)

</div>
