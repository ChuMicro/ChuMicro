# Guide

`chumicro-workspace` is the host-side CLI for a ChuMicro project workspace — a `things/` + `devices.yml` repo cloned from [`ChuMicro/ChuMicro-Workspace-Template`](https://github.com/ChuMicro/ChuMicro-Workspace-Template) (or a fork; see [Decision 0038](https://github.com/ChuMicro/ChuMicro/blob/main/plans/decisions/0038-workspace-bootstrap-via-clone.md)).  It composes [`chumicro-deploy`](https://github.com/ChuMicro/ChuMicro/tree/main/workbench/deploy) and [`chumicro-repl`](https://github.com/ChuMicro/ChuMicro/tree/main/workbench/repl) with the workspace-shaped pieces those packages don't own: a deploy-time config-merge pipeline, a CLI that reads `workspace.yml`, three-zone `devices.yml` round-trip, board-state onboarding, firmware URL derivation, and the boot-shim layout that lets one board host multiple things.

This guide walks through the typical workflows end-to-end.  See the [README](../README.md) for the at-a-glance command list and [API reference](api.md) for the auto-generated module docs.

## Workspace layout

A workspace has this shape:

```
my-workspace/
├── workspace.yml          # defaults + library_sources: + secrets: !secret refs
├── devices.yml            # board registry — three-zone (Decision 0029 §9)
├── secrets.yml            # gitignored — credentials referenced via !secret
├── run.py                 # tiny shim: from chumicro_workspace.cli import main
├── pyproject.toml
├── things/
│   ├── _template/         # `python run.py new` copies from here
│   ├── back-porch/        # one thing
│   │   ├── config.toml
│   │   └── app.py         # def run(): ...
│   └── kitchen/
│       └── ...
├── libs/                  # checked-in user libraries (deploy --import-graph reaches these)
└── packages/              # gitignored, resolved from manifest at sync time
```

The two requirements are `workspace.yml` (`WorkspaceLayout` walks up from cwd to find it, git-style) and `things/`.

## Day-zero: bring up a board

```bash
# Plug a board in, see what serial ports the host exposes.
python run.py discover

# Probe the board over serial — fails with a structured diagnosis if
# the board is in UF2 bootloader mode, the serial port is busy, or
# the runtime doesn't respond.
python run.py add-device back-porch --address /dev/cu.usbmodem1101 --runtime micropython

# `add-device` writes a three-zone entry under devices.yml's `devices:`
# block: id + description + setup_command (user-owned), address (cached
# from the probe — silently refreshed later), runtime (user-owned),
# hardware: { uid, machine, board_id } (hardware-once — re-running
# add-device with --force prompts before overwriting because the user
# might have swapped boards).
```

[`detect_board_state`](api.md) drives onboarding when the probe fails — the four states are `REPL_REACHABLE` (fine), `UF2_BOOTLOADER` (visible mount with `INFO_UF2.TXT`; suggests `install-firmware --method uf2`), `NO_PROBE_RESPONSE` (board on serial but no Python prompt; suggests an esptool reflash), and `SERIAL_UNREACHABLE` (port doesn't open; suggests checking the cable / driver).

## Building a thing

```bash
# Copy the template; edit things/back-porch/{config.toml,app.py}.
python run.py new back-porch
```

`config.toml` carries the per-thing knobs.  Use `!secret <name>` to reference values from `secrets.yml`:

```toml
# things/back-porch/config.toml
[wifi]
ssid = "HomeNet"
password = "!secret wifi_password"

[mqtt]
host = "192.168.1.10"
topic = "things/back-porch/state"
```

`app.py` exports a `run()` function — `workspace_runtime.boot()` calls it after import:

```python
# things/back-porch/app.py
import time

def run():
    print("back-porch coming up")
    while True:
        # ... your thing's main loop ...
        time.sleep(1)
```

## Deploying

### Single thing, default flat layout

```bash
python run.py deploy back-porch
```

Ships the thing's directory contents to the device root via [`thing_directory_source`](api.md): `app.py` lands at `/app.py`, `config.toml` is host-only and skipped, `_generated/` is skipped.  The merged runtime config msgpack rides along at `/runtime_config.msgpack` (the canonical path Decision 0035 §8 reserves).  The device entrypoint is `/code.py` for CircuitPython and `/main.py` for MicroPython by default; override with `--entrypoint`.

### Single thing, AST-walked

```bash
python run.py deploy back-porch --import-graph
```

Routes through [`thing_import_graph_source`](api.md): AST-parses the entrypoint, walks `import` / `from ... import` targets, resolves against the workspace's `libs/` + `packages/` + any `library_sources:` overrides in `workspace.yml`, and ships only the reachable modules.  Useful for things that import shared libs.

### Single thing, boot-shim layout

```bash
python run.py deploy back-porch --boot-shim
```

Stages the [Decision 0029 §3](https://github.com/ChuMicro/ChuMicro/blob/main/plans/decisions/0029-project-workspace.md) on-device shape:

```
/code.py                                  # import workspace_runtime; workspace_runtime.boot()
/active.py                                # THING_NAME = "back-porch"
/runtime_config.msgpack                   # merged config
/lib/workspace_runtime/__init__.py        # boot module
/lib/things/__init__.py
/lib/things/back-porch/
    __init__.py
    app.py
    runtime_config.msgpack
```

`workspace_runtime.boot()` reads `THING_NAME` from `/active.py`, imports `things.back-porch.app`, and calls `app.run()`.

### Multiple things on one device

```bash
python run.py deploy weather heater diagnostic --boot-shim --active weather
```

Ships every named thing side-by-side at `/lib/things/<each>/`, each with its own per-thing runtime config msgpack.  `/active.py` names `weather` so its `run()` fires on boot.

`--active` defaults to the first positional name when omitted.  Multi-thing deploys require `--boot-shim` (the flat layout would collide).

### Switching the active thing

Once multiple things are installed, swap which one runs without re-flashing the payloads:

```bash
python run.py switch heater
```

[`switch_source`](api.md) ships only three small files: `/code.py` (re-staged byte-identical, satisfies the transport's "execute entrypoint" contract), the new `/active.py`, and the new `/runtime_config.msgpack` (the heater thing's merged config).  The thing payloads under `/lib/things/<name>/` stay on flash from the prior multi-thing deploy.

If the named thing's payload isn't on the device, `workspace_runtime.boot()` raises `WorkspaceBootError` on the next boot pointing at "deploy may not have run".  In that case, re-run `deploy --boot-shim ... <name>` to install the payload first.

### Programmatic deploy

The CLI is a thin wrapper over the public Python API.  Build a source explicitly when you need finer control:

```python
from pathlib import Path

from chumicro_deploy import Device, Deployer
from chumicro_workspace import (
    multi_thing_boot_source,
    switch_source,
)
from chumicro_workspace.workspace import WorkspaceLayout

workspace = WorkspaceLayout.from_dir()
device = Device(transport="micropython", address="/dev/cu.usbmodem1101")

# Multi-thing initial deploy.
source = multi_thing_boot_source(
    [workspace.thing_dir("weather"), workspace.thing_dir("heater")],
    workspace=workspace,
    active_thing_name="weather",
    entrypoint_filename="main.py",
)
result = Deployer(device).deploy(source)
assert result.success

# Later: swap to heater.
switch = switch_source(
    workspace.thing_dir("heater"),
    workspace=workspace,
    entrypoint_filename="main.py",
)
Deployer(device).deploy(switch)
```

## Config merge

[`build_runtime_config`](api.md) is the deploy-time pipeline (Decision 0035):

1. Read `workspace.yml`'s `defaults:` block.
2. Read `things/<name>/config.{toml,yml,yaml}`.
3. Read `secrets.yml`.
4. Deep-merge `defaults` ← `thing_config` (thing wins on conflict; lists replace wholesale; dicts recurse).
5. Walk the merged dict, replace every `!secret <name>` string with `secrets[name]` (raises `UnresolvedSecretError` on miss).
6. Pack as msgpack via `chumicro-msgpack`, write to `things/<name>/_generated/runtime_config.msgpack`.

The deploy then ships that msgpack to `/runtime_config.msgpack` on the device.  Apps read it with `chumicro-msgpack`'s `unpackb`.

To regenerate the msgpack without deploying — useful in tests or pre-flight checks:

```python
from pathlib import Path
from chumicro_workspace import build_runtime_config

build_runtime_config(
    workspace_yaml=Path("workspace.yml"),
    thing_config=Path("things/back-porch/config.toml"),
    secrets_yaml=Path("secrets.yml"),
    output_path=Path("things/back-porch/_generated/runtime_config.msgpack"),
)
```

## Firmware

```bash
# CircuitPython: latest stable from the Adafruit S3 bucket.
python run.py install-firmware --method uf2

# MicroPython: latest dated build from micropython.org/download/<BOARD>/.
python run.py install-firmware --method esptool

# Pre-release windows (CP only):
python run.py install-firmware --method uf2 --allow-prerelease

# Vendor / custom URL pinned in devices.yml:
# devices.yml entry sets hardware.firmware_source: "https://my-mirror/...uf2"
python run.py install-firmware --method uf2     # picks up firmware_source

# Or override at the call site:
python run.py install-firmware --url https://example/custom.uf2 --method uf2
```

[`derive_firmware_url`](api.md) routes the choice:

1. `hardware.firmware_source` set → return verbatim.
2. Runtime is CircuitPython → S3 bucket listing → latest stable.
3. Runtime is MicroPython → curated machine→BOARD map → micropython.org scrape → latest stable dated build.

ESP32-family boards need `.bin` instead of `.uf2`; set `hardware.firmware_extension = "bin"` in the device entry to route the MP scrape there.

## `devices.yml` round-trip

The package uses `ruamel.yaml` to preserve user comments and field ordering across read-modify-write cycles.  PyYAML can't honor either — it discards comments and sorts keys alphabetically — so every mutator routes through [`load_devices`](api.md) → mutator → [`dump_devices`](api.md):

```python
from pathlib import Path
from chumicro_workspace import (
    load_devices, dump_devices, update_device_address, HardwareOverwriteError,
)

devices = load_devices(Path("devices.yml"))
update_device_address(devices, "back-porch", "/dev/cu.usbmodem1102")
dump_devices(Path("devices.yml"), devices)
```

`update_device_hardware` raises `HardwareOverwriteError` when a hardware-once leaf would change; pass `force=True` to override (the swap-boards case).  `rename_device` also rewrites `defaults.<runtime>` references that point at the old id.

## Workbench-only

This package runs on CPython only — never on a microcontroller.  Workbench tools and scripts (the workspace's `run.py` shim) consume it; the on-device side of the workspace contract is `chumicro-config` ([Decision 0036](https://github.com/ChuMicro/ChuMicro/blob/main/plans/decisions/0036-chumicro-config-library.md)).
