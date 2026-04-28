# chumicro-workspace

Host-side runtime for ChuMicro project workspaces.  Wraps `chumicro-deploy` and `chumicro-repl` with the workspace-shaped conventions a `things/`-and-`devices.yml` repo expects: deploy-time config merge, a CLI that reads `workspace.yml`, three-zone `devices.yml` round-trip, board-state onboarding, firmware URL derivation, an import-graph deploy mode, and the boot-shim layout that boots a single thing through the `workspace_runtime` indirection.

Part of the [ChuMicro](https://github.com/ChuMicro/ChuMicro) workspace.  Workbench tool — runs on your laptop to drive connected boards.  See [Decision 0032](https://github.com/ChuMicro/ChuMicro/blob/main/plans/decisions/0032-workbench-host-tools.md) for the workbench pattern, [Decision 0029](https://github.com/ChuMicro/ChuMicro/blob/main/plans/decisions/0029-project-workspace.md) for the workspace contract, and [Decision 0035](https://github.com/ChuMicro/ChuMicro/blob/main/plans/decisions/0035-runtime-config-structure.md) for the config-merge story.

## Status

Project-workspace Phase 4a feature-complete + workspace-ecosystem Phases 1, 2, 4, 5 shipped (2026-04-27).  The package consolidates everything Decision 0029 / 0035 / 0038 specified plus the user-friendliness pass that followed: nested thing namespaces, an `examples/` folder for read-and-scaffold demos, `status` / `doctor` health snapshots, `deploy --dry-run`, `deploy --all-devices`, `repl <thing>` one-shot deploy + tail, app-level deploy-failure recovery hints, `new --library` for chumicro-style libraries, and `workspace.yml` `quality:` knob wiring (`lint.enabled` / `lint.select` / `coverage_threshold` / `agent_strictness`).  The `switch` command + multi-thing staging path retired in 2026-04-27 — single-thing deploys via `thing_boot_source` are the canonical shape.  The canonical workspace template ships as a separate Git repo at [`ChuMicro/ChuMicro-Workspace-Template`](https://github.com/ChuMicro/ChuMicro-Workspace-Template); `init` / `update` orchestrate cloning + tool-owned re-flow.

## What's here today

### CLI

The package ships `python -m chumicro_workspace` (also exposed as the `chumicro-workspace` console script and consumed via the workspace template's `run.py` shim).

| Command | Purpose |
|---|---|
| `init <target> [--from <url>] [--ref <branch>]` | Clone the canonical workspace template into *target*.  `setup` is the natural follow-up. |
| `setup` | `pip install -e .` the workspace's pyproject + materialize `_templates/` files (one-time per clone; idempotent). |
| `update [--ref <branch>]` | Pull tool-owned file refreshes from the template upstream — re-flows `_templates/`, `examples/`, `things/_template/`, `.github/skills/`, `run.py`, `AGENTS.md`, `CONTRIBUTING.md`, `pyproject.toml`.  User-owned files (your `things/`, `secrets.yml`, `devices.yml`, `workspace.yml`, `libs/`, `packages/`) untouched. |
| `bootstrap [--port <p>] [--device-id <id>] [--with-demo]` | End-to-end onboarding wizard: pick a port → probe runtime → register the device → optionally deploy the demo payload. |
| `new <path> [--from <example>]` | Scaffold a new thing under `things/<path>/`.  *path* accepts bare / slash / dotted forms; intermediate namespace dirs auto-created.  `--from <example>` copies an `examples/<x>/` tree instead of `things/_template/`. |
| `new <name> --library [--into <dir>]` | Scaffold a chumicro-style library tree (`src/chumicro_<name>/`, tests, docs, examples).  Defaults to `<workspace>/libraries/<name>/`. |
| `add-device <id> --address <port> [--runtime <cp\|mp>] [--description <text>] [--force]` | Probe a board and write the entry into `devices.yml`.  Runtime auto-detected when omitted. |
| `probe` | Print the runtime identity reported by the selected board. |
| `discover` | List the serial ports the host currently sees. |
| `devices` | Print every entry in `devices.yml`. |
| `things [--flat]` | Default Unicode tree view; `--flat` for one-line-per-thing slash-form output. |
| `status` | One-line-per-check workspace health snapshot — `workspace.yml` validity, `devices.yml` count, `secrets.yml` placeholder detection, things-tree summary. |
| `doctor` | Strict sibling of `status` — adds Python ≥3.11 check, per-thing AST scan for `def run`, and a config-merge dry-run that catches unresolved `!secret` references. |
| `deploy <name> [--boot-shim] [--import-graph] [--dry-run] [--all-devices] [--wipe]` | Ship a thing.  *name* accepts bare / slash / dotted (with bare-name disambiguation against the live tree).  `--dry-run` prints the file map without writing.  `--all-devices` loops over every entry in `devices.yml`.  `--wipe` erases the device filesystem before deploying (destructive — clean-slate / corruption recovery only). |
| `demo` | Deploy a built-in print-loop payload to the active device (no wifi, ~5s).  Useful as the first-deploy sanity check. |
| `repl [--tail SECONDS] [<thing>]` | Interactive REPL by default.  `--tail SECONDS` captures output for a window.  Optional positional thing deploys then tails (default 30s window). |
| `install-firmware [--url URL] --method <uf2\|esptool>` | Download + flash firmware (URL auto-derived from `hardware.firmware_source` / `hardware.board_id` / `hardware.machine` when omitted). |
| `upgrade-firmware` | Alias of `install-firmware`. |
| `rename --thing OLD NEW \| --device OLD NEW` | Rename a thing dir (slash/dotted on both sides; intermediate namespaces auto-created) or a `devices.yml` entry id. |
| `test [-- ...]` | Run pytest at the workspace root.  Workspace.yml `quality.coverage_threshold` (when set) prepends `--cov-fail-under=N`. |
| `lint [-- ...]` | Run `ruff check`.  Workspace.yml `quality.lint.enabled = false` skips with a hint; `quality.lint.select` prepends `--select <list>`. |
| `sim`, `env`, `use` | Stubbed — emit a "registered, not yet implemented" message. |
| `sync`, `upgrade` | Deprecated aliases for `update` — emit a "superseded by `update`" message. |

### Boot-shim layout

`deploy --boot-shim <name>` ships the [Decision 0029 §3](https://github.com/ChuMicro/ChuMicro/blob/main/plans/decisions/0029-project-workspace.md) on-device shape.  Nested thing names produce a parallel namespace tree under `/lib/things/`:

```
/code.py                              # two-line shim: import workspace_runtime; boot()
/active.py                            # THING_NAME = "garage.sensors.door_open"
/runtime_config.msgpack               # merged config
/lib/workspace_runtime/__init__.py    # boot module — imports things.<dotted>.app and calls run()
/lib/things/__init__.py               # package marker
/lib/things/garage/__init__.py        # namespace marker (one per level)
/lib/things/garage/sensors/__init__.py
/lib/things/garage/sensors/door_open/ # the thing's files
    __init__.py
    app.py
```

For a flat single-segment thing the layout collapses to the
single-level shape (`/lib/things/<name>/`).

The original Phase 4a multi-thing-on-one-device path
(`deploy --boot-shim foo bar baz --active foo` + a `switch <name>`
command for re-pointing `/active.py`) was retired in Slice 7 of
the nested-things-and-examples workstream — it blew the flash
budget on Decision 0015 minimum boards and the "instant switch"
pitch wasn't worth the cost.  See [`plans/next-up.md`'s "Replace
multi-thing staging with scoped diff-deploy" entry](https://github.com/ChuMicro/ChuMicro/blob/main/plans/next-up.md)
for the workstream that replaces it.

### Public Python API

```python
from chumicro_workspace import (
    # Config merge (Decision 0035)
    build_runtime_config,        # all sources -> merged dict -> msgpack
    merge_configs,               # deep per-key merge of two or more dicts
    resolve_secrets,             # walk a value, replace !secret <name> refs
    read_workspace_yaml,         # parse workspace.yml -> defaults dict
    read_thing_config,           # parse things/<name>/config.{toml,yml,yaml}
    read_secrets_yaml,           # parse secrets.yml -> dict (empty when absent)
    write_runtime_config,        # write merged dict to msgpack at given path
    UnresolvedSecretError,       # !secret <name> resolved against missing key
    WorkspaceConfigError,        # YAML/TOML top-level shape malformed

    # Deploy sources
    WithRuntimeConfig,           # FileSource decorator that injects the msgpack
    thing_directory_source,      # flat layout: thing dir at device root
    thing_boot_source,           # boot-shim layout: thing under /lib/things/<...>/<name>/
    thing_import_graph_source,   # AST-walked layout: only reachable modules

    # devices.yml three-zone round-trip (Decision 0029 §9)
    add_device,                  # add a probed entry, prompting on hardware-once changes
    update_device_address,       # silent address refresh (probed-always zone)
    update_device_hardware,      # raises HardwareOverwriteError on hardware-once collision
    rename_device,               # rewrites entry id + defaults: references
    set_runtime_default,         # pin defaults.<runtime> = <id>
    load_devices,                # ruamel-backed read preserving comments + order
    dump_devices,                # atomic write preserving comments + order

    # Onboarding (Decision 0029 §4)
    BoardState,                  # REPL_REACHABLE / UF2_BOOTLOADER / NO_PROBE_RESPONSE / SERIAL_UNREACHABLE
    OnboardingDiagnosis,
    detect_board_state,          # picks the right next-steps message
    find_uf2_drive,              # scan for INFO_UF2.TXT mounts

    # Firmware URL derivation (Decision 0029 §5)
    derive_firmware_url,         # entry -> URL via firmware_source / S3 / micropython.org
    latest_circuitpython_url,
    latest_micropython_url,      # micropython.org/download/<BOARD>/ scrape
    list_circuitpython_versions,
    list_micropython_builds,
    micropython_board_for_machine,
    UnresolvableFirmwareError,

    # Import-graph (Decision 0029 §6+§7)
    build_search_paths,          # libs/ + packages/ + library_sources: overrides
    read_library_sources,        # workspace.yml's library_sources: block

    # Constants
    RUNTIME_CONFIG_DEVICE_PATH,  # "/runtime_config.msgpack"
    GENERATED_DIRNAME,           # "_generated"
    BOOT_MODULE_DEVICE_PATH,
    THINGS_PACKAGE_INIT_DEVICE_PATH,
    SHIM_ENTRYPOINT_SOURCE,
)

# Workspace-ecosystem add-ons (Phases 1–5)
from chumicro_workspace.workspace import (
    ThingClassification,         # THING / NAMESPACE / SUPPORTING
    WorkspaceLayout,             # gains list_things() recursive walk + iter_things_with_classification()
)
from chumicro_workspace.health import (
    HealthFinding,               # one row in status / doctor
    HealthLevel,                 # OK / WARN / ERROR
    SECRET_PLACEHOLDER,          # the canonical "replace-me" sentinel
    collect_health_findings,     # status's four checks
    collect_doctor_findings,     # doctor's seven checks
)
from chumicro_workspace.recovery import (
    AppErrorHint,                # one matched-pattern hint
    detect_hints,                # traceback → list[AppErrorHint]
    format_hints,                # render the --- hints --- block
)
from chumicro_workspace.scaffold import (
    LibraryAlreadyExistsError,
    scaffold_library,            # create a chumicro-style library tree
)
from chumicro_workspace.quality import (
    LintConfig,                  # lint sub-config (enabled, select)
    QualityConfig,               # workspace.yml quality: block, typed
    load_quality_config,         # parse + validate the block
)
```

See [`docs/guide.md`](docs/guide.md) for end-to-end walkthroughs and [`docs/api.md`](docs/api.md) for the auto-generated reference.

## Install

```bash
pip install chumicro-workspace
```

The package lives on the host only; nothing in it lands on a microcontroller.  The on-device boot module ships as a payload that the `--boot-shim` deploy stages onto the device under `/lib/workspace_runtime/`.

## License

[MIT](https://github.com/ChuMicro/ChuMicro/blob/main/LICENSE)
