# Guide

`chumicro-workspace` is the host-side CLI for running ChuMicro projects on real boards from your laptop.  It composes [`chumicro-deploy`](https://chumicro.github.io/ChuMicro/deploy/stable/) and [`chumicro-repl`](https://chumicro.github.io/ChuMicro/repl/stable/) with the workspace-shaped pieces those packages don't own: a deploy-time config-merge pipeline, a CLI that reads `workspace.yml`, three-zone `devices.yml` round-trip, board-state onboarding, firmware URL derivation, and the boot-shim layout that lets one board host multiple projects.

This guide walks through the typical workflows end-to-end.  See the [API reference](api.md) for auto-generated module docs.

## Workspace layout

A workspace has this shape:

```
my-workspace/
├── workspace.yml          # gitignored — defaults + library_sources + your credentials
├── devices.yml            # board registry — three-zone (defaults / devices / device-credentials)
├── pyproject.toml
├── projects/
│   ├── _template/         # `chumicro-workspace new` copies from here
│   ├── back-porch/        # one project
│   │   ├── config.toml
│   │   └── app.py         # def run(): ...
│   └── kitchen/
│       └── ...
├── shared/                # flat shared modules — `from shared.foo import bar`
├── libraries/             # full chumicro-style library packages (scaffolded via `new --library`)
│   └── buttons/
│       ├── src/chumicro_buttons/
│       ├── tests/
│       ├── docs/
│       └── pyproject.toml
└── packages/              # gitignored, resolved from manifest at sync time
```

The two requirements are `workspace.yml` (`WorkspaceLayout` walks up from cwd to find it, git-style) and `projects/`.

### `shared/` vs `libraries/` — when to use each

Both hold code your projects can `import`.  Pick by *weight*:

| Want to ship… | Drop it under | Imports look like | Notes |
|---|---|---|---|
| A 50-line helper your projects share | `shared/foo.py` | `from shared.foo import bar` | No tests, no version, no scaffolding. |
| A full chumicro-style library you might publish someday | `libraries/<name>/` (via `new --library`) | `import <name>` | Gets `src/`, `tests/`, `docs/`, `examples/`, `pyproject.toml`, `VERSION` — the standard publishable-library layout. |
| A third-party package | `packages/` (via `sync`) | `import <name>` | Gitignored mirror cache. |

The import-graph search path resolves in this order: explicit `library_sources:` overrides → `shared/` → every `libraries/<name>/src/` (auto-discovered) → `packages/`. So a library scaffolded with `new --library buttons` is importable as `import buttons` from any project without further wiring.

## Day-zero: bring up a board

The fastest path is the `bootstrap` wizard — pick a port, probe the runtime, register the device, and (optionally) deploy the built-in demo payload in one shot:

```bash
chumicro-workspace bootstrap --with-demo
```

For non-interactive runs (CI, scripted setup), pass `--port` and `--device-id` explicitly:

```bash
chumicro-workspace bootstrap --port /dev/cu.usbmodem1101 --device-id back-porch
```

The slower-but-explicit path is what `bootstrap` composes:

```bash
# Plug a board in, see what serial ports the host exposes.
chumicro-workspace discover

# Probe the board over serial — fails with a structured diagnosis if
# the board is in UF2 bootloader mode, the serial port is busy, or
# the runtime doesn't respond.  Runtime auto-detected when --runtime
# is omitted (probes both transports).
chumicro-workspace add-device back-porch --address /dev/cu.usbmodem1101 --runtime micropython

# `add-device` writes a three-zone entry under devices.yml's `devices:`
# block: id + description (user-owned), address (cached
# from the probe — silently refreshed later), runtime (user-owned),
# hardware: { uid, machine, board_id } (hardware-once — re-running
# add-device with --force prompts before overwriting because the user
# might have swapped boards).
```

[`detect_board_state`](api.md) drives onboarding when the probe fails — the four states are `REPL_REACHABLE` (fine), `UF2_BOOTLOADER` (visible mount with `INFO_UF2.TXT`; suggests `install-firmware --method uf2`), `NO_PROBE_RESPONSE` (board on serial but no Python prompt; suggests an esptool reflash), and `SERIAL_UNREACHABLE` (port doesn't open; suggests checking the cable / driver).

## Workspace health

`status` is the one-screen "is anything obviously broken" check.  Every `deploy` runs the same fast checks as a pre-flight gate — ERROR-level findings (malformed `workspace.yml` / `devices.yml`) abort before sending bytes to the device; WARN-level findings (no devices registered yet, etc.) print but proceed.  Pass `deploy --skip-health-check` to skip the gate (CI / power-user flows).

Run it directly to see the snapshot:

```bash
chumicro-workspace status
# WORKSPACE              /Users/you/projects/my-house
# WORKSPACE.YML          ✓ valid
# DEVICES.YML            ✓ 2 devices registered
# PROJECTS               ✓ 4 projects: garage/sensors/door_open, …
```

`doctor` is the strict sibling — runs every status check plus a Python-version probe and an AST scan for `def run` in each project's `app.py`:

```bash
chumicro-workspace doctor
# Adds rows for PYTHON and PROJECT run() defs.
# Exit code is 1 only on ERROR-level findings; warnings stay 0 so
# the command composes cleanly with shell-pipe checks.
```

## Building a project

```bash
# Copy projects/_template/ into projects/back-porch/.
chumicro-workspace new back-porch

# Nested layouts are supported — intermediate namespace dirs are
# auto-created with empty __init__.py markers so host-side imports
# (`from projects.garage.sensors.door_open.app import run`) work.
chumicro-workspace new garage/sensors/door_open
chumicro-workspace new garage.sensors.door_open      # dotted form, same effect

# Scaffold from a worked example instead of the blank template.
chumicro-workspace new garage/heater --from examples/wifi_only

# Scaffold a chumicro-style library (full src/tests/docs/examples
# tree).  Lands at <workspace>/libraries/<name>/ by default;
# --into <dir> overrides.
chumicro-workspace new gpio --library
```

### How config flows from your edits to the device

The runtime config a project receives at boot is the deep-merge of two gitignored host-side sources, both sharing the same section-namespaced shape:

```
workspace.yml ──────────────────► projects/<name>/config.toml
  (gitignored — workspace-wide       (gitignored when scaffolded by `new`;
   defaults + your credentials        per-project knobs — sample period,
   in one place)                      mqtt topic, sensor pins)

                            │
                            ▼
                        merge_configs                  ← chumicro_workspace.merge
                            │                              (deep per-key merge:
                            ▼                               higher-precedence layer
                                                            wins at any key)
                        packb (msgpack)                ← chumicro_workspace.writer
                            │                              (use_single_float=True so
                            ▼                               CircuitPython's native
              /runtime_config.msgpack on device            msgpack module accepts it)
                            │
                            ▼
                     chumicro_config.runtime           ← READS the msgpack on the device
```

Use `chumicro-workspace dump-config <project>` to print the merged dict your project would receive without actually deploying — useful for debugging which layer a key landed in.

`config.toml` carries the per-project knobs; `workspace.yml` carries workspace-wide defaults plus your credentials (the file is gitignored, so credentials never reach git):

```toml
# projects/back-porch/config.toml — gitignored when scaffolded by `new`
[wifi]
ssid = "HomeNet"

[mqtt]
host = "192.168.1.10"
topic = "projects/back-porch/state"
```

```yaml
# workspace.yml — gitignored; defaults flow into every project that doesn't override
defaults:
  wifi:
    password: my-real-wifi-password
```

`app.py` exports a `run()` function — `workspace_runtime.boot()` calls it after import:

```python
# projects/back-porch/app.py
import time

def run():
    print("back-porch coming up")
    while True:
        # ... your project's main loop ...
        time.sleep(1)
```

## Deploying

### Single project, default flat layout

```bash
chumicro-workspace deploy back-porch
```

Ships the project's directory contents to the device root via [`project_directory_source`](api.md): `app.py` lands at `/app.py`, `config.toml` is host-only and skipped, `_generated/` is skipped.  The merged runtime config msgpack rides along at `/runtime_config.msgpack` (the path the on-device `chumicro_config.load_runtime_config()` reads).  The device entrypoint is `/code.py` for CircuitPython and `/main.py` for MicroPython by default; override with `--entrypoint`.

### Single project, AST-walked

```bash
chumicro-workspace deploy back-porch --import-graph
```

Routes through [`project_import_graph_source`](api.md): AST-parses the entrypoint, walks `import` / `from ... import` targets, resolves against the workspace's `shared/` + `packages/` + any `library_sources:` overrides in `workspace.yml`, and ships only the reachable modules.  Useful for projects that import shared libs.

### Single project, boot-shim layout

```bash
chumicro-workspace deploy back-porch --boot-shim
```

Stages the on-device project layout:

```
/code.py                                  # import workspace_runtime; workspace_runtime.boot()
/active.py                                # PROJECT_NAME = "back-porch"
/runtime_config.msgpack                   # merged config
/lib/workspace_runtime/__init__.py        # boot module
/lib/projects/__init__.py
/lib/projects/back-porch/
    __init__.py
    app.py
    runtime_config.msgpack
```

`workspace_runtime.boot()` reads `PROJECT_NAME` from `/active.py`, imports `projects.back-porch.app`, and calls `app.run()`.

### Nested project names

Slash- or dotted-form project names produce a parallel namespace tree under `/lib/projects/`.  `chumicro-workspace deploy garage/sensors/door_open --boot-shim` lays down:

```
/lib/projects/__init__.py
/lib/projects/garage/__init__.py
/lib/projects/garage/sensors/__init__.py
/lib/projects/garage/sensors/door_open/
    __init__.py
    app.py
```

`/active.py` carries the dotted form (`PROJECT_NAME = "garage.sensors.door_open"`); `workspace_runtime.boot()` concatenates `"projects." + PROJECT_NAME + ".app"` and Python's import machinery walks the namespace inits to the leaf.

### Inspect what would land — `--dry-run`

```bash
chumicro-workspace deploy garage/sensors/door_open --boot-shim --dry-run
```

Builds the source like a real deploy, but prints the file map (path / size / one-word category) instead of calling the transport.  Useful when:

* The structural overlay merge produced something unexpected — the runtime config msgpack appears in the listing with its real size.
* You're sanity-checking a nested layout — every per-level `__init__.py` shows up classified as `namespace`, so a missing one is obvious.
* You want to read what deploy actually does — the output's stable shape doubles as documentation.

Categories: `shim` (workspace-runtime infrastructure), `namespace` (empty `__init__.py` markers), `project` (the project's own files), `config` (the runtime-config msgpack), `library` (anything else under `/lib/` — typically import-graph-resolved deps), `file` (anything at the device root — typically flat-layout deploys).

### One project per `deploy` call

Multi-project-on-one-device deploys (`deploy <a> <b> <c> --boot-shim`) and the matching `switch <name>` re-pointer were retired — multi-project-staging blew the flash budget on the minimum supported board class (256 KB MCU RAM / 4 MB flash).  Pass one positional per `deploy` invocation; re-deploy when you want to change which project is active.  Scoped diff-deploy is the replacement (`deploy_diff` on the transport layer, `deploy --wipe` for a clean slate).

### Multi-board deploys — `--all-devices`

```bash
chumicro-workspace deploy garage/door_open --all-devices
```

Loops over every entry in `devices.yml` and ships the project to each in declaration order.  Per-device failures don't abort the loop; the exit code is 1 if any device's deploy failed, 0 otherwise.  Mutually exclusive with `--device` / `--runtime` (caught at runtime with a precise message).

### Per-project default device — `deploy_targets:`

When a workspace has multiple boards, typing `--device <id>` for every deploy gets tedious.  `workspace.yml`'s `deploy_targets:` block carries a per-project → per-device default; a bare `deploy <project>` (no `--device` / `--runtime`) then picks the project's mapped target.  Falls back to `devices.yml`'s `defaults:` block for unmapped projects.

```yaml
deploy_targets:
  garage/door: pi-pico-w-circuitpython-board   # bare string OK
  garage/window: [lolin-s2-circuitpython-board]
  garage/server:                               # multiple → list
    - pi-pico-w-micropython-board
    - lolin-s2-micropython-board
```

`deploy --all-projects` walks the whole mapping at once — every project to every device it lists, in declaration order.  Mutually exclusive with positional names / `--device` / `--runtime` / `--all-devices`.  Per-(project, device) failures don't abort the loop; exit code reflects whether any failed.  Empty / missing `deploy_targets:` block exits 2 with a hint.

### Clean-slate deploys — `--wipe`

```bash
chumicro-workspace deploy garage/door_open --wipe
```

Erases the entire device filesystem before staging the new payload — destructive, wipes user-managed files (`settings.toml`, uploaded assets, hand-edited `boot.py`) along with managed deploy scope.  Use for corruption recovery, freeing space, or any "I want a known-empty board before this deploy" situation; ordinary deploys already clean stale `/lib/*` files via the diff-deploy primitive, so reach for `--wipe` only when the diff isn't enough.

CircuitPython drives `import storage; storage.erase_filesystem()` (which reformats the FAT volume and reboots the board); MicroPython walks the user filesystem and removes every file + directory.  Firmware partitions are untouched on both runtimes.  No-op in RAM-mode deploys (RAM never wrote to flash, nothing to wipe).

### Failure hints

When the deploy traceback matches a known workspace-shaped pattern, an indented `--- hints ---` block prints below it pointing at the fix:

* `NameError: name '<sym>' is not defined` → "did you forget to import…"
* `OSError ... runtime_config.msgpack` → "RAM-mode deploys don't persist the config msgpack — switch to flash mode."
* `ImportError`/`ModuleNotFoundError ... chumicro_*` → "library not installed in this venv — run `chumicro-workspace setup`."
* `KeyError: '<key>'` → "missing config key — check `projects/<project>/config.toml` or `workspace.yml`'s `defaults:` block (the gitignored workspace config carrying defaults + credentials)."

Driven by [`detect_hints`](api.md) over the captured traceback + execute output.  Empty hints → no section header (so unmatched failures don't carry an empty heading).

### Programmatic deploy

The CLI is a thin wrapper over the public Python API.  Build a source explicitly when you need finer control:

```python
from chumicro_deploy import Device, Deployer
from chumicro_workspace import project_boot_source
from chumicro_workspace.workspace import WorkspaceLayout

workspace = WorkspaceLayout.from_dir()
device = Device(transport="micropython", address="/dev/cu.usbmodem1101")

source = project_boot_source(
    workspace.project_dir("garage/sensors/door_open"),
    workspace=workspace,
    project_name="garage/sensors/door_open",
    entrypoint_filename="main.py",
)
result = Deployer(device).deploy(source)
assert result.success
```

## REPL

```bash
# Interactive REPL on the default device.
chumicro-workspace repl

# Tail-only — stream output for a window, then exit.  Useful for
# CI / scripted "watch the next 30 seconds" checks.
chumicro-workspace repl --tail 30

# Deploy then tail in one command — replaces the
# `deploy <project> && repl --tail` two-command idiom.  Default tail
# window is 30s; --tail SECONDS overrides.
chumicro-workspace repl garage/sensors/door_open
chumicro-workspace repl garage/sensors/door_open --tail 60
```

The deploy half of `repl <project>` uses [`project_boot_source`](api.md) — for flat-layout deploys, run `deploy` and `repl --tail` separately.

## Quality knobs

`workspace.yml`'s `quality:` block carries pass-through knobs the workspace CLI consults:

```yaml
quality:
  lint:
    enabled: true
    select: ["E", "F", "I"]
  coverage_threshold: 85
```

* `lint.enabled = false` → `chumicro-workspace lint` becomes a no-op + hint (still discoverable; just doesn't run ruff).
* `lint.select` → forwarded to ruff as `--select <comma list>` before any user `--` passthrough so user overrides win.
* `coverage_threshold` → forwarded to pytest as `--cov-fail-under=<n>`.  Lets workspace.yml gate without editing pyproject.toml's `[tool.coverage.report]`.

Loader: [`load_quality_config`](api.md).  Missing block → permissive defaults (lint enabled, no coverage gate) — wiring is purely opt-in.  Shape violations raise `WorkspaceConfigError` with a precise field-named message.

## Config merge

[`build_runtime_config`](api.md) is the deploy-time pipeline:

1. Read `workspace.yml`'s `defaults:` block (gitignored — workspace-wide defaults + credentials in one place).
2. Read `projects/<name>/config.{toml,yml,yaml}`.
3. Deep-merge in that order (later layer wins at any nesting depth; lists replace wholesale; dicts recurse).
4. Pack as msgpack via the standard `msgpack` library (with `use_single_float=True` for CircuitPython compatibility), write to `projects/<name>/_generated/runtime_config.msgpack`.

The deploy then ships that msgpack to `/runtime_config.msgpack` on the device.  Apps read it via `chumicro-config`'s `load_runtime_config()`.

To regenerate the msgpack without deploying — useful in tests or pre-flight checks:

```python
from pathlib import Path
from chumicro_workspace import build_runtime_config

build_runtime_config(
    workspace_yaml=Path("workspace.yml"),
    project_config=Path("projects/back-porch/config.toml"),
    output_path=Path("projects/back-porch/_generated/runtime_config.msgpack"),
)
```

## Firmware

```bash
# CircuitPython: latest stable from the Adafruit S3 bucket.
chumicro-workspace install-firmware --method uf2

# MicroPython: latest dated build from micropython.org/download/<BOARD>/.
chumicro-workspace install-firmware --method esptool

# Pre-release windows (CP only):
chumicro-workspace install-firmware --method uf2 --allow-prerelease

# Vendor / custom URL pinned in devices.yml:
# devices.yml entry sets hardware.firmware_source: "https://my-mirror/...uf2"
chumicro-workspace install-firmware --method uf2     # picks up firmware_source

# Or override at the call site:
chumicro-workspace install-firmware --url https://example/custom.uf2 --method uf2
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

`update_device_hardware` raises `HardwareOverwriteError` when a hardware-once leaf would change; pass `force=True` to override (the swap-boards case).  `rename_device` also rewrites `defaults.<runtime>` references that point at the old id; `remove_device` deletes an entry and nulls any `defaults.<runtime>` that pointed at it (so the file stays loadable), returning the removed entry for callers that re-register under the same id.

## Workbench-only

This package runs on CPython only — never on a microcontroller.  The on-device side of the workspace contract is [`chumicro-config`](https://chumicro.github.io/ChuMicro/config/stable/).

---

<div class="chumicro-footer" markdown>

[← Home](index.md)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/workbench/workspace) · \
[PyPI](https://pypi.org/project/chumicro-workspace/) · \
[Issues](https://github.com/ChuMicro/ChuMicro/issues)

</div>
