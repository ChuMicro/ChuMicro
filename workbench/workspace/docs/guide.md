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
├── libs/                  # flat shared modules — `from libs.foo import bar`
├── libraries/             # full chumicro-style library packages (scaffolded via `new --library`)
│   └── buttons/
│       ├── src/chumicro_buttons/
│       ├── tests/
│       ├── docs/
│       └── pyproject.toml
└── packages/              # gitignored, resolved from manifest at sync time
```

The two requirements are `workspace.yml` (`WorkspaceLayout` walks up from cwd to find it, git-style) and `things/`.

### `libs/` vs `libraries/` — when to use each

Both hold code your things can `import`.  Pick by *weight*:

| Want to ship… | Drop it under | Imports look like | Notes |
|---|---|---|---|
| A 50-line helper your things share | `libs/foo.py` | `from libs.foo import bar` | No tests, no version, no scaffolding. |
| A full chumicro-style library you might publish someday | `libraries/<name>/` (via `new --library`) | `import <name>` | Gets `src/`, `tests/`, `docs/`, `examples/`, `pyproject.toml`, `VERSION` — same shape the chumicro mono-repo uses. |
| A third-party package | `packages/` (via `sync`) | `import <name>` | Gitignored mirror cache. |

The import-graph search path resolves in this order: explicit `library_sources:` overrides → `libs/` → every `libraries/<name>/src/` (auto-discovered) → `packages/`. So a library scaffolded with `new --library buttons` is importable as `import buttons` from any thing without further wiring.

## Day-zero: bring up a board

The fastest path is the `bootstrap` wizard — pick a port, probe the runtime, register the device, and (optionally) deploy the built-in demo payload in one shot:

```bash
python run.py bootstrap --with-demo
```

For non-interactive runs (CI, scripted setup), pass `--port` and `--device-id` explicitly:

```bash
python run.py bootstrap --port /dev/cu.usbmodem1101 --device-id back-porch
```

The slower-but-explicit path is what `bootstrap` composes:

```bash
# Plug a board in, see what serial ports the host exposes.
python run.py discover

# Probe the board over serial — fails with a structured diagnosis if
# the board is in UF2 bootloader mode, the serial port is busy, or
# the runtime doesn't respond.  Runtime auto-detected when --runtime
# is omitted (probes both transports).
python run.py add-device back-porch --address /dev/cu.usbmodem1101 --runtime micropython

# `add-device` writes a three-zone entry under devices.yml's `devices:`
# block: id + description + setup_command (user-owned), address (cached
# from the probe — silently refreshed later), runtime (user-owned),
# hardware: { uid, machine, board_id } (hardware-once — re-running
# add-device with --force prompts before overwriting because the user
# might have swapped boards).
```

[`detect_board_state`](api.md) drives onboarding when the probe fails — the four states are `REPL_REACHABLE` (fine), `UF2_BOOTLOADER` (visible mount with `INFO_UF2.TXT`; suggests `install-firmware --method uf2`), `NO_PROBE_RESPONSE` (board on serial but no Python prompt; suggests an esptool reflash), and `SERIAL_UNREACHABLE` (port doesn't open; suggests checking the cable / driver).

## Workspace health

`status` is the one-screen "is anything obviously broken" check.  Every `deploy` runs the same fast checks as a pre-flight gate — ERROR-level findings (malformed `workspace.yml` / `devices.yml` / `secrets.yml`) abort before sending bytes to the device; WARN-level findings (placeholder secrets, no devices registered yet) print but proceed.  Pass `deploy --skip-health-check` to skip the gate (CI / power-user flows).

Run it directly to see the snapshot:

```bash
python run.py status
# WORKSPACE       /Users/you/projects/my-house
# WORKSPACE.YML   ✓ valid
# DEVICES.YML     ✓ 2 devices registered
# SECRETS.YML     ⚠ placeholder values: wifi_password
#                   hint: edit secrets.yml — replace `replace-me` …
# THINGS          ✓ 4 things: garage/sensors/door_open, …
```

`doctor` is the strict sibling — runs every status check plus a Python-version probe, an AST scan for `def run` in each thing's `app.py`, and a config-merge dry-run that catches `!secret` references with no matching key:

```bash
python run.py doctor
# Adds rows for PYTHON, THING run() defs, SECRET refs.
# Exit code is 1 only on ERROR-level findings; warnings stay 0 so
# the command composes cleanly with shell-pipe checks.
```

## Building a thing

```bash
# Copy things/_template/ into things/back-porch/.
python run.py new back-porch

# Nested layouts are first-class — intermediate namespace dirs are
# auto-created with empty __init__.py markers so host-side imports
# (`from things.garage.sensors.door_open.app import run`) work.
python run.py new garage/sensors/door_open
python run.py new garage.sensors.door_open      # dotted form, same effect

# Scaffold from a worked example instead of the blank template.
python run.py new garage/heater --from examples/wifi_only

# Scaffold a chumicro-style library (full src/tests/docs/examples
# tree).  Lands at <workspace>/libraries/<name>/ by default;
# --into <dir> overrides.
python run.py new gpio --library
```

### How config flows from your edits to the device

The runtime config a thing receives at boot is the merge of three host-side sources, with secret references resolved at deploy time:

```
secrets.yml                workspace.yml              things/<name>/config.toml
   (host)                     (host)                          (host)
      │                          │                              │
      └──────────────┬───────────┴──────────────────────────────┘
                     ▼
                 merge_configs                  ← chumicro_workspace.merge
                     │                              (deep per-key merge: thing
                     ▼                               wins over workspace defaults)
                 resolve_secrets                ← chumicro_workspace.secrets
                     │                              (replaces "!secret <name>"
                     ▼                               → secrets.yml value)
                 packb (msgpack)                ← chumicro_workspace.writer
                     │                              (use_single_float=True so
                     ▼                               CircuitPython's native
       /runtime_config.msgpack on device            msgpack module accepts it)
                     │
                     ▼
              chumicro_config.runtime           ← READS the msgpack on the device
```

Use `chumicro-workspace dump-config <thing>` to print the merged dict your thing would receive without actually deploying — useful for "is this `!secret` resolving to what I think it is?" debugging.

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

### Nested thing names

Slash- or dotted-form thing names produce a parallel namespace tree under `/lib/things/`.  `python run.py deploy garage/sensors/door_open --boot-shim` lays down:

```
/lib/things/__init__.py
/lib/things/garage/__init__.py
/lib/things/garage/sensors/__init__.py
/lib/things/garage/sensors/door_open/
    __init__.py
    app.py
```

`/active.py` carries the dotted form (`THING_NAME = "garage.sensors.door_open"`); `workspace_runtime.boot()` concatenates `"things." + THING_NAME + ".app"` and Python's import machinery walks the namespace inits to the leaf.

### Inspect what would land — `--dry-run`

```bash
python run.py deploy garage/sensors/door_open --boot-shim --dry-run
```

Builds the source like a real deploy, but prints the file map (path / size / one-word category) instead of calling the transport.  Useful when:

* The `!secret` merge produced something unexpected — the runtime config msgpack appears in the listing with its real size.
* You're sanity-checking a nested layout — every per-level `__init__.py` shows up classified as `namespace`, so a missing one is obvious.
* You want to read what deploy actually does — the output's stable shape doubles as documentation.

Categories: `shim` (workspace-runtime infrastructure), `namespace` (empty `__init__.py` markers), `thing` (the thing's own files), `config` (the runtime-config msgpack), `library` (anything else under `/lib/` — typically import-graph-resolved deps), `file` (anything at the device root — typically flat-layout deploys).

### One thing per `deploy` call

Multi-thing-on-one-device deploys (`deploy <a> <b> <c> --boot-shim`) and the matching `switch <name>` re-pointer were retired in Slice 7 of the nested-things-and-examples workstream — multi-thing-staging blew the flash budget on Decision 0015 minimum boards.  Pass one positional per `deploy` invocation; re-deploy when you want to change which thing is active.  See [`plans/next-up.md`'s "Replace multi-thing staging with scoped diff-deploy" entry](https://github.com/ChuMicro/ChuMicro/blob/main/plans/next-up.md) for the workstream that replaces it.

### Multi-board deploys — `--all-devices`

```bash
python run.py deploy garage/door_open --all-devices
```

Loops over every entry in `devices.yml` and ships the thing to each in declaration order.  Per-device failures don't abort the loop; the exit code is 1 if any device's deploy failed, 0 otherwise.  Mutually exclusive with `--device` / `--runtime` (caught at runtime with a precise message).

### Clean-slate deploys — `--wipe`

```bash
python run.py deploy garage/door_open --wipe
```

Erases the entire device filesystem before staging the new payload — destructive, wipes user-managed files (`settings.toml`, uploaded assets, hand-edited `boot.py`) along with managed deploy scope.  Use for corruption recovery, freeing space, or any "I want a known-empty board before this deploy" situation; ordinary deploys already clean stale `/lib/*` files via the diff-deploy primitive, so reach for `--wipe` only when the diff isn't enough.

CircuitPython drives `import storage; storage.erase_filesystem()` (which reformats the FAT volume and reboots the board); MicroPython walks the user filesystem and removes every file + directory.  Firmware partitions are untouched on both runtimes.  No-op in RAM-mode deploys (RAM never wrote to flash, nothing to wipe).

### Failure hints

When the deploy traceback matches a known workspace-shaped pattern, an indented `--- hints ---` block prints below it pointing at the fix:

* `NameError: name '<sym>' is not defined` → "did you forget to import…"
* `ValueError ... !secret <name>` → "secrets.yml has no entry for `<name>`…"
* `OSError ... runtime_config.msgpack` → "RAM-mode deploys don't persist the config msgpack — switch to flash mode."
* `ImportError`/`ModuleNotFoundError ... chumicro_*` → "library not installed in this venv — run `python run.py setup`."
* `KeyError: '<key>'` → "missing config key — check `things/<thing>/config.toml` or `workspace.yml`'s `[defaults]` block."

Driven by [`detect_hints`](api.md) over the captured traceback + execute output.  Empty hints → no section header (so unmatched failures don't carry an empty heading).

### Programmatic deploy

The CLI is a thin wrapper over the public Python API.  Build a source explicitly when you need finer control:

```python
from chumicro_deploy import Device, Deployer
from chumicro_workspace import thing_boot_source
from chumicro_workspace.workspace import WorkspaceLayout

workspace = WorkspaceLayout.from_dir()
device = Device(transport="micropython", address="/dev/cu.usbmodem1101")

source = thing_boot_source(
    workspace.thing_dir("garage/sensors/door_open"),
    workspace=workspace,
    thing_name="garage/sensors/door_open",
    entrypoint_filename="main.py",
)
result = Deployer(device).deploy(source)
assert result.success
```

## REPL

```bash
# Interactive REPL on the default device.
python run.py repl

# Tail-only — stream output for a window, then exit.  Useful for
# CI / scripted "watch the next 30 seconds" checks.
python run.py repl --tail 30

# Deploy then tail in one command (Phase 2e).  Replaces the
# `deploy <thing> && repl --tail` two-command idiom.  Default tail
# window is 30s; --tail SECONDS overrides.
python run.py repl garage/sensors/door_open
python run.py repl garage/sensors/door_open --tail 60
```

The deploy half of `repl <thing>` uses [`thing_boot_source`](api.md) — for flat-layout deploys, run `deploy` and `repl --tail` separately.

## Quality knobs

`workspace.yml`'s `quality:` block carries four pass-through knobs the workspace CLI consults:

```yaml
quality:
  lint:
    enabled: true
    select: ["E", "F", "I"]
  coverage_threshold: 85
  agent_strictness: relaxed   # or "strict"
```

* `lint.enabled = false` → `python run.py lint` becomes a no-op + hint (still discoverable; just doesn't run ruff).
* `lint.select` → forwarded to ruff as `--select <comma list>` before any user `--` passthrough so user overrides win.
* `coverage_threshold` → forwarded to pytest as `--cov-fail-under=<n>`.  Lets workspace.yml gate without editing pyproject.toml's `[tool.coverage.report]`.
* `agent_strictness` — accepted today, AST-level enforcement (no naked `except:`, no global state in things) deferred to a later workstream.

Loader: [`load_quality_config`](api.md).  Missing block → permissive defaults (lint enabled, no coverage gate, agent relaxed) — wiring is purely opt-in.  Shape violations raise `WorkspaceConfigError` with a precise field-named message.

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
