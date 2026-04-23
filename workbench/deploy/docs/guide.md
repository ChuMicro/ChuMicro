# User Guide

This guide walks through everything `chumicro-deploy` offers today — from the `Device` struct to `Deployer.deploy()`, file sources, probing, and firmware URL resolution. Flashing firmware (`flash_firmware`) is planned for a near-future release; it is not yet available.

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
| CircuitPython | inline raw-REPL exec (used by the test harness; **not** supported by `Deployer.deploy()` today) | write to CIRCUITPY drive, soft-reboot, capture output |

`Deployer.deploy()` on CircuitPython currently requires `deploy_mode="flash"`. A RAM-mode deploy for CP would need on-the-fly module injection, which is deliberately deferred — use flash mode or the lower-level `stage()` / `execute()` flow until that lands.

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

1. Classifies the error into a `DeployFailureKind` — one of `PORT_UNAVAILABLE`, `RAW_REPL_UNRESPONSIVE`, `CIRCUITPY_DRIVE_MISSING`, `FLASH_COPY_FAILED`, `BOOTSTRAP_EXEC_FAILED`, `INSUFFICIENT_MEMORY`, `CONFIGURATION_ERROR`, or `UNKNOWN`.
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

### Try it against real boards

[`workbench/deploy/functional_tests/demo_recovery_hand_holding.py`](https://github.com/ChuMicro/ChuMicro/blob/main/workbench/deploy/functional_tests/demo_recovery_hand_holding.py) walks every configured `devices.yml` board through each failure scenario and prints the coaching output live.  Run it when you want to see what the CLI actually says to the user on a real cable-out / drive-ejected / board-rebooted failure.

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
