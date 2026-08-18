# Guide

`chumicro-workspace` is the host-side CLI for running ChuMicro projects on real boards from your laptop.  It builds on [`chumicro-deploy`](https://chumicro.com/ChuMicro/deploy/stable/) for the transports, firmware flashing, and the `devices.yml` schema, and picks up [`chumicro-repl`](https://chumicro.com/ChuMicro/repl/stable/) when you ask for an interactive session or a tail.  On top of those it adds the workspace-shaped pieces: a deploy-time config merge, a CLI that reads `workspace.yml`, board-state onboarding, firmware URL derivation, and the boot shim that lets a project ship an `app.py` with a `run()` instead of hand-writing a `code.py`.

This guide walks through the typical workflows end to end.  See the [API reference](api.md) for the module-level docs.

## Workspace layout

A workspace has this shape:

```
my-workspace/
├── workspace.yml          # workspace machinery: library_sources, deploy_targets, quality
├── secrets.toml           # workspace-wide credentials and device defaults
├── devices.yml            # board registry
├── pyproject.toml
├── projects/
│   ├── _template/         # `chumicro-workspace new` copies from here
│   ├── back-porch/        # one project
│   │   ├── project_config.toml
│   │   └── app.py         # def run(): ...
│   └── kitchen/
│       └── ...
├── shared/                # flat shared modules, imported by bare name
├── libraries/             # full chumicro-style library packages (`new <name> --library`)
│   └── buttons/
│       ├── src/chumicro_buttons/
│       ├── tests/
│       ├── docs/
│       └── pyproject.toml
└── packages/              # third-party modules you vendor in yourself
```

The two requirements are `workspace.yml` (`WorkspaceLayout` walks up from cwd to find it, git-style) and `projects/`.

`secrets.toml` holds real wifi passwords and broker credentials, so never commit it.  `workspace.yml` and `devices.yml` carry machine-specific paths and board ids, so most workspaces keep those out of git as well.  Check what your `.gitignore` covers before the first commit.

### `shared/` vs `libraries/`: when to use each

Both hold code your projects can `import`.  Pick by weight:

| Want to ship… | Drop it under | Imports look like | Notes |
|---|---|---|---|
| A 50-line helper your projects share | `shared/foo.py` | `from foo import bar` | No tests, no version, no scaffolding.  The search path roots at `shared/` itself, so there is no `shared.` prefix to qualify against. |
| A full chumicro-style library you might publish someday | `libraries/<name>/` (via `new <name> --library`) | `import <name>` | Gets `src/`, `tests/`, `docs/`, `examples/`, `pyproject.toml`, and `VERSION`: the standard publishable-library layout. |
| A published chumicro library | `libraries/<name>/` (via `library add <name>`) | `import chumicro_<name>` | Fetched from the release channel along with the chumicro libraries it imports.  A re-fetch backs up a tree you have edited instead of clobbering it. |
| A third-party module you vendor yourself | `packages/` | `import <name>` | Nothing populates this for you.  Drop files in and the search path finds them last. |

The import-graph search path resolves in this order: explicit `library_sources:` overrides, then `shared/`, then every `libraries/<name>/src/` (auto-discovered), then `packages/`.  So a library scaffolded with `new buttons --library` is importable as `import buttons` from any project without further wiring.

Getting the `shared/` spelling wrong is the common first stumble.  A module at `shared/foo.py` is `from foo import bar`, never `from shared.foo import bar`, and a deploy that hits the wrong spelling says so before it ships anything.

## Day-zero: bring up a board

The fastest path is `bootstrap`: it picks a port, probes the runtime, registers the board in `devices.yml`, and prints what to run next.

```bash
chumicro-workspace bootstrap
```

Run interactively it fills in the blanks for you, auto-picking the only serial port it sees or prompting with a numbered list when there are several.  Add `--demo` to chain into the built-in demo deploy so a freshly registered board ships something in the same command.  For CI or scripted setup, name the id and the port outright:

```bash
chumicro-workspace bootstrap back-porch --address /dev/cu.usbmodem1101 --non-interactive
```

`bootstrap` installs no firmware and opens no REPL.  It is `add-device` plus a next-steps footer, so if a board needs firmware first, see [Firmware](#firmware) below.

The slower and more explicit path is what `bootstrap` composes:

```bash
# Plug a board in, see what serial ports the host exposes.
chumicro-workspace discover

# Probe the board over serial.  Fails with a structured diagnosis if
# the board is in UF2 bootloader mode, the serial port is busy, or
# the runtime doesn't respond.  Runtime is auto-detected when
# --runtime is omitted (it tries both transports).
chumicro-workspace add-device back-porch --address /dev/cu.usbmodem1101 --runtime micropython
```

### The three `devices.yml` zones

`add-device` writes an entry under `devices.yml`'s `devices:` block, and every later command rewrites the file in place with your comments and field order intact.  Which fields a rewrite may touch depends on the zone:

| Zone | Fields | Rewrite rule |
|---|---|---|
| User-owned | `id`, `description`, `deploy_mode`, `serial_baudrate` | Yours.  Nothing overwrites them. |
| Probed-always | `address`, `firmware_version` | Refreshed silently on every probe, because a board moves between ports. |
| Hardware-once | `runtime`, and the `hardware:` block (`uid`, `machine`, `board_id`, `firmware_source`) | Written once.  Changing one needs an explicit `--force`, because a changed uid usually means you swapped boards. |

[`detect_board_state`](api.md) drives onboarding when the probe fails.  The four states are `REPL_REACHABLE` (fine), `UF2_BOOTLOADER` (a visible mount with `INFO_UF2.TXT`, which suggests `install-firmware --method uf2`), `NO_PROBE_RESPONSE` (board on serial but no Python prompt, which suggests an esptool reflash), and `SERIAL_UNREACHABLE` (the port doesn't open, so check the cable and the driver).

## Workspace health

`status` is the one-screen "is anything obviously broken" check.  Every `deploy` runs the same fast checks as a pre-flight gate: ERROR-level findings (a malformed `workspace.yml` or `devices.yml`) abort before any bytes reach the device, while WARN-level findings (no devices registered yet, for instance) print and let the deploy proceed.  Pass `deploy --skip-health-check` to skip the gate in CI or power-user flows.

Run it directly to see the snapshot:

```bash
chumicro-workspace status
# WORKSPACE              /Users/you/projects/my-house
# WORKSPACE.YML          ✓ valid
# DEVICES.YML            ✓ 2 devices registered
# PROJECTS               ✓ 4 projects: garage/sensors/door_open, …
```

`doctor` is the strict sibling.  It runs every `status` check plus a Python-version probe and an AST scan for `def run` in each project's `app.py`:

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

# Nested layouts work too.  Intermediate namespace directories are
# created for you with empty __init__.py markers, so host-side imports
# (`from projects.garage.sensors.door_open.app import run`) resolve.
chumicro-workspace new garage/sensors/door_open
chumicro-workspace new garage.sensors.door_open      # dotted form, same effect

# Copy an existing tree instead of the blank template.  --from takes any
# directory under the workspace root that contains an app.py, code.py,
# or main.py entry point.
chumicro-workspace new garage/heater --from examples/two_board_handshake/server

# Scaffold a chumicro-style library (full src/tests/docs/examples tree).
# Lands at <workspace>/libraries/<name>/ by default; --into <dir>
# overrides.  --workbench scaffolds a host-only tool the same way.
chumicro-workspace new gpio --library
```

### How config flows from your edits to the device

The runtime config a project receives at boot is the deep-merge of two host-side files, both using the same `[section]`-keyed TOML shape:

```
secrets.toml                       projects/<name>/project_config.toml
  workspace-wide credentials         per-project knobs: sample period,
  and device defaults, in one        mqtt topic, sensor pins.  Wins on
  place.  Keep it out of git.        any key both files set.
              │                                   │
              └────────────────┬──────────────────┘
                               ▼
                        merge_configs           ← chumicro_workspace.merge
                               │                  (deep per-key merge: dicts
                               ▼                   recurse, lists replace)
                       flatten_config           ← chumicro_workspace.flatten
                               │                  ([wifi] ssid becomes the
                               ▼                   flat key "wifi.ssid")
                    write_runtime_config        ← chumicro_workspace.writer
                               │                  (use_single_float=True so
                               ▼                   CircuitPython's built-in
          /runtime_config.msgpack on device        msgpack module accepts it)
                               │
                               ▼
                   chumicro_config.runtime      ← reads it on the device
```

`workspace.yml` is separate.  It carries workspace **machinery** (`library_sources`, `deploy_targets`, `quality`, the curated `libraries` table), not runtime config, and nothing from it lands on the device.

Use `chumicro-workspace dump-config <project>` to print the merged dict your project would receive without deploying anything.  It is the fastest way to find out which file a key came from.

`secrets.toml` carries credentials and workspace-wide device defaults; `project_config.toml` carries the per-project knobs:

```toml
# secrets.toml: values flow into every project that doesn't override them
[wifi]
ssid = "HomeNet"
password = "my-real-wifi-password"
```

```toml
# projects/back-porch/project_config.toml
[mqtt]
host = "192.168.1.10"
topic = "projects/back-porch/state"
```

`app.py` exports a `run()` function, which the synthesised entrypoint shim imports and calls:

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

Two things vary independently.  The *layout* decides what file map gets built (flat, boot-shim, import-graph, or boot-shim plus import-graph) and deploy picks it from the shape of your project.  The *deploy mode* decides where the files land: `flash` writes them to the board's filesystem so they survive a reset, `ram` pushes them into memory for a fast throwaway run.  A device's mode lives in its `devices.yml` entry, and `--deploy-mode {ram,flash}` overrides it for one run.

### Single project, default flat layout

```bash
chumicro-workspace deploy back-porch
```

Ships the project's directory contents to the device root via [`project_directory_source`](api.md): `app.py` lands at `/app.py`, `project_config.toml` is host-only and skipped, `_generated/` is skipped.  The merged runtime config msgpack rides along at `/runtime_config.msgpack` (the path the on-device `chumicro_config.load_runtime_config()` reads).  The device entrypoint is `/code.py` for CircuitPython and `/main.py` for MicroPython by default; override with `--entrypoint`.

### Single project, AST-walked

```bash
chumicro-workspace deploy back-porch --import-graph
```

Routes through [`project_import_graph_source`](api.md): it AST-parses the entrypoint, walks the `import` and `from ... import` targets, resolves them against the workspace's `shared/`, `libraries/<name>/src/`, and `packages/` directories plus any `library_sources:` overrides in `workspace.yml`, and ships only the modules it reached.  Use it when a project imports shared code you don't want to copy by hand.

### Installing libraries without the workspace tooling

The default path pulls chumicro libraries into the workspace with `chumicro-workspace library add <name>`, then `deploy --import-graph` ships the ones a project imports to the board's `/lib/`.  Both steps fetch from the host's network.

When the host can't reach the snapshot channel (air-gapped, behind a custom registry, or simply offline), install onto the board directly with the runtime's own package manager.  Both pull from `ChuMicro-Bundle`, take the libraries your project imports, and resolve transitive chumicro dependencies for you:

```bash
# CircuitPython: register the bundle once per machine, then install by name
circup bundle-add ChuMicro/ChuMicro-Bundle
circup install chumicro_wifi chumicro_mqtt chumicro_runner

# MicroPython: one mip install per library, and the board needs wifi to fetch
mpremote connect /dev/cu.usbmodem1101 mip install \
    github:ChuMicro/ChuMicro-Bundle/chumicro_wifi
mpremote connect /dev/cu.usbmodem1101 mip install \
    github:ChuMicro/ChuMicro-Bundle/chumicro_mqtt
```

`circup` uses hyphens (`chumicro-wifi`); `mip` uses the underscore import name (`chumicro_wifi`).  Swap `ChuMicro-Bundle` for `ChuMicro-Bundle-Experimental` to track the pre-release channel.  Files land at `/lib/chumicro_<name>/` either way, the same place `deploy --import-graph` writes them, so a project deployed afterward finds its imports.  Full install matrix, pre-compiled `.mpy` bytecode, and pip-on-CPython: [INSTALL.md](https://github.com/ChuMicro/ChuMicro/blob/main/INSTALL.md).

### Pointing the library channel at a mirror

`library add`, `browse`, and `update` fetch from GitHub by default.  Two environment variables move the channel to any server that carries the same tree layout, over `https`, `http`, or `file`:

```bash
export CHUMICRO_CHANNEL_FILES_BASE="https://mirror.example"     # replaces raw.githubusercontent.com
export CHUMICRO_CHANNEL_TARBALLS_BASE="https://mirror.example"  # replaces codeload.github.com
```

The URL paths keep the GitHub shapes (`<owner>/<repo>/<ref>/<path>` for raw files, `<owner>/<repo>/tar.gz/refs/tags/<tag>` for snapshot tarballs), so a mirror is a plain directory tree.  `python -m http.server` and a `file://` base both work.  The same seam exercises the acquisition path against a locally staged channel before any live repo exists.

### Single project, boot-shim layout

A project that ships `app.py` with a top-level `run()` and no `code.py` / `main.py` of its own gets this layout automatically, so you rarely pass the flag by hand:

```bash
chumicro-workspace deploy back-porch --boot-shim
```

Your project's files land at the device root, and deploy synthesises the entrypoint next to them:

```
/code.py                  # synthesised, three lines (or /main.py on MicroPython)
/app.py                   # your code: def run(): ...
/helpers.py               # anything else in the project directory
/runtime_config.msgpack   # merged config
```

The synthesised file is exactly this, and deploy overwrites it every time, so don't edit it on the board:

```python
# Shipped by chumicro-workspace; do not edit.
from app import run as _run
_run()
```

Only the runtime-matching filename is written, never both.  Deploy owns that one file; you own everything else at the device root.

Combine it with `--import-graph` to also ship the libraries `app.py` imports to `/lib/`, which is what the auto-detected path does when a project reaches for chumicro libraries.

### One project per board

A board runs one project at a time.  To change which one, deploy the other.

Staging several projects on one board (the old `deploy <a> <b> <c>` form and the `switch` command that went with it) was removed: the staged copies overran the flash budget on the smallest supported board class, 256 KB of MCU RAM with 2 MB physical flash and roughly 800 KB usable.  Pass one project name per `deploy` call.  Ordinary deploys already remove stale files, and `deploy --wipe` gives you a known-empty board when you want one.

### Inspect what would land with `--dry-run`

```bash
chumicro-workspace deploy garage/sensors/door_open --dry-run
```

Builds the file map like a real deploy, then prints it (path, size, one-word category) instead of calling the transport.  Useful when:

* You want to confirm the runtime config actually made it in.  The msgpack shows up in the listing with its real size.
* A library you expected isn't reaching the board.  Anything under `/lib/` is categorised `library`, so a short list means the import walk didn't find it.
* You want to read what deploy actually does.  The output's shape is stable enough to serve as documentation.

The categories are `shim` (`/code.py` or `/main.py`, which is the firmware entrypoint no matter who wrote it), `config` (`/runtime_config.msgpack`), `library` (anything under `/lib/`), and `file` (everything else at the device root).

### Multi-board deploys with `--all-devices`

```bash
chumicro-workspace deploy garage/door_open --all-devices
```

Loops over every entry in `devices.yml` and ships the project to each in declaration order.  Per-device failures don't abort the loop; the exit code is 1 if any device's deploy failed, 0 otherwise.  Mutually exclusive with `--device` / `--runtime` (caught at runtime with a precise message).

### Per-project default device with `deploy_targets:`

When a workspace has several boards, typing `--device <id>` for every deploy gets tedious.  `workspace.yml`'s `deploy_targets:` block maps each project to its default device or devices, so a bare `deploy <project>` with no `--device` or `--runtime` picks the mapped target.  Projects that aren't in the mapping fall back to `devices.yml`'s `defaults:` block.

```yaml
deploy_targets:
  garage/door: pi-pico-w-circuitpython-board   # a bare string is fine
  garage/window: [lolin-s2-circuitpython-board]
  garage/server:                               # several devices, so a list
    - pi-pico-w-micropython-board
    - lolin-s2-micropython-board
```

`deploy --all-projects` walks the whole mapping at once, every project to every device it lists, in declaration order.  It is mutually exclusive with positional names, `--device`, `--runtime`, and `--all-devices`.  A failure on one (project, device) pair doesn't abort the loop, and the exit code reflects whether any failed.  An empty or missing `deploy_targets:` block exits 2 with a hint.

### Clean-slate deploys with `--wipe`

```bash
chumicro-workspace deploy garage/door_open --wipe
```

A plain `deploy` is already clean-slate: it removes anything on the board that isn't part of the new payload, apart from a small keep set the device itself needs (`boot.py`, `boot_out.txt`, `_chu_kv.msgpack`).  A board-resident `settings.toml` is evicted, because it competes with config-driven wifi.

Three levels, from gentlest to harshest:

| Flag | What survives |
|---|---|
| `--no-wipe` | Everything you put on the board by hand.  Only the entrypoint, the state files, and `/lib` get reconciled. |
| (default) | The keep set.  Everything else that isn't the new payload goes. |
| `--wipe` | Nothing.  The whole filesystem is erased before the payload is staged, keep set included. |

Reach for `--wipe` when the board is corrupted or you want a provably empty starting point.  CircuitPython runs `import storage; storage.erase_filesystem()`, which reformats the FAT volume and reboots the board; MicroPython walks the user filesystem and removes every file and directory.  Firmware partitions are untouched on both runtimes, and the flag is a no-op in RAM-mode deploys since nothing was written to flash.

### Failure hints

When the deploy traceback matches a known workspace-shaped pattern, an indented `--- hints ---` block prints below it pointing at the fix:

* `NameError: name '<sym>' is not defined` points at the missing `from ... import ...` in `app.py`.
* `OSError ... runtime_config.msgpack` explains that RAM-mode deploys don't persist the config msgpack, and to switch the device to flash mode.
* `ImportError` or `ModuleNotFoundError` naming a `chumicro_*` module says the library isn't installed in this venv and suggests re-running `setup`.
* `KeyError: '<key>'` names the missing config key and points at `projects/<project>/project_config.toml` and `secrets.toml`.

Driven by [`detect_hints`](api.md) over the captured traceback and execute output.  When nothing matches, no header prints, so unmatched failures don't carry an empty heading.

### Programmatic deploy

The CLI is a thin wrapper over the Python API.  Build a source explicitly when you need finer control:

```python
from chumicro_deploy import Device, Deployer
from chumicro_workspace.boot_shim import project_boot_source
from chumicro_workspace.workspace import WorkspaceLayout

workspace = WorkspaceLayout.from_dir()
device = Device(transport="micropython", address="/dev/cu.usbmodem1101")

source = project_boot_source(
    workspace.project_dir("garage/sensors/door_open"),
    workspace=workspace,
    entrypoint_filename="main.py",
)
result = Deployer(device).deploy_diff(source)
assert result.success
```

`deploy_diff` is the one deploy entry point: it asks the transport what is currently on the board, deletes what the new payload doesn't include, then writes and runs.

## REPL

```bash
# Interactive REPL on the default device.
chumicro-workspace repl

# Tail only: stream output for a window, then exit.  Useful for CI and
# scripted "watch the next 30 seconds" checks.
chumicro-workspace repl --tail 30
```

`repl` takes no project name.  To deploy and then watch in one command, put the tail on the deploy:

```bash
chumicro-workspace deploy garage/sensors/door_open --tail
chumicro-workspace deploy garage/sensors/door_open --tail 60
```

`--tail` defaults to 30 seconds when you give it no number, and needs exactly one project and one device.  It exits non-zero if a traceback shows up in the tailed output; pass `--no-fail-on-traceback` when that isn't what you want.

## Quality knobs

`lint`, `test`, and `preflight` read their gates from two files.  `quality.toml` at the workspace root is the committed policy that travels with the repo, and `workspace.yml`'s `quality:` block is the per-machine override that wins on any key it sets.

```toml
# quality.toml: shared policy, committed
coverage_threshold = 85    # top-level keys go before any [table]

[lint]
enabled = true
tools = ["ruff", "chumicro-checks"]
select = ["E", "F", "I"]
```

```yaml
# workspace.yml: your machine's overrides
quality:
  lint:
    enabled: false
```

The knobs:

* `lint.enabled = false` turns `lint` into a no-op that prints a hint, so the command stays discoverable but runs nothing.
* `lint.tools` picks which tools run.  The default runs both `ruff` and `chumicro-checks`; drop one to disable it without disabling the whole phase.  An empty list behaves like `enabled = false`, and a name outside the known set is rejected at load time so a typo surfaces instead of silently skipping a tool.
* `lint.select` is forwarded to ruff as `--select <comma list>` ahead of anything you pass after `--`, so your own arguments still win.
* `coverage_threshold` is forwarded to pytest as `--cov-fail-under=<n>`, which lets you set the gate without editing `pyproject.toml`'s `[tool.coverage.report]`.

[`load_quality_config`](api.md) reads both files, validates each one separately so an error names the file that carries it, and merges them.  With neither file present you get permissive defaults: linting on, no coverage gate.  A malformed shape raises `WorkspaceConfigError` naming the offending field.

## Config merge

[`build_runtime_config`](api.md) is the deploy-time pipeline:

1. Read `secrets.toml`, the workspace-wide credentials and device defaults.
2. Read `projects/<name>/project_config.toml`.
3. Deep-merge in that order.  The later layer wins at any nesting depth, dicts recurse, and lists replace wholesale.
4. Flatten nested tables to dotted keys, so `[wifi] ssid` becomes `"wifi.ssid"`.  The device-side reader works with the flat shape: one hash lookup per key, no recursion.
5. Pack as msgpack via the standard `msgpack` library with `use_single_float=True` for CircuitPython, and write to `projects/<name>/_generated/runtime_config.msgpack`.

The deploy then ships that msgpack to `/runtime_config.msgpack` on the device, where apps read it via `chumicro-config`'s `load_runtime_config()`.

`compose_runtime_config` runs the same steps and hands back the dict without writing anything, which is what you want in tests.  To regenerate the msgpack on disk without deploying:

```python
from pathlib import Path
from chumicro_workspace.pipeline import build_runtime_config

build_runtime_config(
    secrets_toml=Path("secrets.toml"),
    project_config=Path("projects/back-porch/project_config.toml"),
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

# Vendor or custom URL pinned in devices.yml, where the device entry
# sets hardware.firmware_source: "https://my-mirror/...uf2"
chumicro-workspace install-firmware --method uf2     # picks up firmware_source

# Or override at the call site:
chumicro-workspace install-firmware --url https://example/custom.uf2 --method uf2
```

With no `--url`, the URL is derived from the device entry in this order, by `derive_firmware_url` in [`chumicro-deploy`](https://chumicro.com/ChuMicro/deploy/stable/api/):

1. `hardware.firmware_source` is set, so it is returned verbatim.
2. The runtime is CircuitPython, so the Adafruit S3 bucket listing gives the latest stable build.
3. The runtime is MicroPython, so a curated machine-to-BOARD map plus a micropython.org lookup gives the latest stable dated build.

ESP32-family boards need `.bin` instead of `.uf2`.  Set `hardware.firmware_extension = "bin"` in the device entry to point the MicroPython lookup at the right file.

`chumicro-workspace` also checks whether a board's installed firmware is new enough for the libraries you are deploying; see [`check_firmware_supported`](api.md).

## `devices.yml` round-trip

`devices.yml` is yours to comment and order however you like, and every rewrite preserves both.  That comes from `ruamel.yaml`, which round-trips comments and key order where PyYAML discards comments and sorts keys alphabetically.

The schema and its writers live in `chumicro-deploy`, which owns the file.  Every mutation is load, mutate, dump:

```python
from pathlib import Path
from chumicro_deploy.config.devices_yaml import (
    HardwareOverwriteError,
    dump_devices,
    load_devices,
    update_device_address,
)

devices = load_devices(Path("devices.yml"))
update_device_address(devices, "back-porch", "/dev/cu.usbmodem1102")
dump_devices(devices, Path("devices.yml"))
```

`update_device_hardware` raises `HardwareOverwriteError` when a hardware-once field would change; pass `force=True` when you really did swap boards.  `rename_device` also rewrites any `defaults.<runtime>` reference pointing at the old id.  `remove_device` deletes an entry, nulls any `defaults.<runtime>` that pointed at it so the file stays loadable, and returns the removed entry for callers that want to re-register under the same id.

## Workbench-only

This package runs on CPython and never on a microcontroller.  The on-device side of the workspace contract is [`chumicro-config`](https://chumicro.com/ChuMicro/config/stable/).

---

<div class="chumicro-footer" markdown>

[← Home](index.md)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/workbench/workspace) · \
[PyPI](https://pypi.org/project/chumicro-workspace/) · \
[Issues](https://github.com/ChuMicro/ChuMicro/issues)

</div>
