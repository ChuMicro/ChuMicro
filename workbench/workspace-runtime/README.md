# chumicro-workspace-runtime

Host-side runtime for ChuMicro project workspaces.  Wraps `chumicro-deploy` and `chumicro-repl` with the workspace-shaped conventions a `things/`-and-`devices.yml` repo expects: deploy-time config merge, a CLI that reads `workspace.yml`, three-zone `devices.yml` round-trip, board-state onboarding, firmware URL derivation, an import-graph deploy mode, and the boot-shim layout that lets one board host multiple things.

Part of the [ChuMicro](https://github.com/ChuMicro/ChuMicro) workspace.  Workbench tool — runs on your laptop to drive connected boards.  See [Decision 0032](https://github.com/ChuMicro/ChuMicro/blob/main/plans/decisions/0032-workbench-host-tools.md) for the workbench pattern, [Decision 0029](https://github.com/ChuMicro/ChuMicro/blob/main/plans/decisions/0029-project-workspace.md) for the workspace contract, and [Decision 0035](https://github.com/ChuMicro/ChuMicro/blob/main/plans/decisions/0035-runtime-config-structure.md) for the config-merge story.

## Status

Phase 4a feature-complete.  Seven slices closed end-to-end (config-merge core, deploy integration, CLI dispatch + 17+ commands, three-zone `devices.yml` writer, board-state onboarding, firmware URL derivation, import-graph resolver, boot-shim layout) plus the multi-thing-on-one-device follow-on.  Phase 4b (`chumicro-workspace-template`) is the next deliverable; it consumes this package's API.

## What's here today

### CLI

The package ships `python -m chumicro_workspace_runtime` (also exposed as the `chumicro-workspace-runtime` console script and consumed via the workspace template's `run.py` shim).

| Command | Purpose |
|---|---|
| `setup` | `pip install -e .` the workspace's pyproject (one-time per clone). |
| `new <name>` | `cp -r things/_template things/<name>` to start a new thing. |
| `add-device <id> --address <port> --runtime <cp\|mp>` | Probe a board and write the entry into `devices.yml`. |
| `probe` | Print the runtime identity reported by the selected board. |
| `discover` | List the serial ports the host currently sees. |
| `devices` | Print every entry in `devices.yml`. |
| `things` | Print every thing under `things/` (skips `_template` and `_`-prefixed dirs). |
| `deploy <name> [<more> ...] [--boot-shim] [--import-graph] [--active <name>]` | Ship one or more things to a board. |
| `switch <name>` | Re-point `/active.py` at a different thing already on the device — fast (3 files), no payload re-flash. |
| `repl [--tail SECONDS]` | Open an interactive REPL or stream output for a window. |
| `install-firmware [--url URL] --method <uf2\|esptool>` | Download + flash firmware (URL auto-derived from `hardware.firmware_source` / `hardware.board_id` / `hardware.machine` when omitted). |
| `upgrade-firmware` | Alias of `install-firmware`. |
| `rename --thing OLD NEW \| --device OLD NEW` | Rename a thing dir or a `devices.yml` entry id. |
| `test [-- ...]` | Run pytest at the workspace root; extra args pass through after `--`. |
| `sim`, `env`, `use`, `sync`, `upgrade` | Stubbed for later slices / Phase 4b — emit a "registered, not yet implemented" message. |

### Boot-shim layout

`deploy --boot-shim <name>` ships the [Decision 0029 §3](https://github.com/ChuMicro/ChuMicro/blob/main/plans/decisions/0029-project-workspace.md) on-device shape:

```
/code.py                              # two-line shim: import workspace_runtime; boot()
/active.py                            # THING_NAME = "<name>"
/runtime_config.msgpack               # merged config (active thing's view)
/lib/workspace_runtime/__init__.py    # boot module — imports things.<name>.app and calls run()
/lib/things/__init__.py               # package marker
/lib/things/<name>/                   # the thing's files (app.py, helpers, etc.)
    __init__.py
    app.py
    runtime_config.msgpack            # per-thing copy (multi-thing flows read this)
```

### Multi-thing on one device

`deploy --boot-shim foo bar baz --active foo` ships every named thing side-by-side under `/lib/things/<each>/` with per-thing runtime config msgpacks.  The active thing's msgpack is also written at the canonical `/runtime_config.msgpack` so existing app code that reads from there keeps working.

`switch <name>` then re-points `/active.py` (and the canonical msgpack) without re-shipping payloads — three small files instead of the whole stack.  Use cases: dev/diagnostic vs production thing on one board, A/B testing two firmware variants, a shop-demo device that cycles through several apps.

### Public Python API

```python
from chumicro_workspace_runtime import (
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
    thing_boot_source,           # boot-shim layout: thing under /lib/things/<name>/
    thing_import_graph_source,   # AST-walked layout: only reachable modules

    # Multi-thing + switch (boot-shim layout only)
    multi_thing_boot_source,     # ship N things side-by-side
    multi_thing_boot_files,      # static shim layer for a multi-thing layout
    switch_source,               # FileMapSource that re-points /active.py
    build_switch_files,          # the three-file switch payload, callable directly

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
```

See [`docs/guide.md`](docs/guide.md) for end-to-end walkthroughs and [`docs/api.md`](docs/api.md) for the auto-generated reference.

## Install

```bash
pip install chumicro-workspace-runtime
```

The package lives on the host only; nothing in it lands on a microcontroller.  The on-device boot module ships as a payload that the `--boot-shim` deploy stages onto the device under `/lib/workspace_runtime/`.

## License

[MIT](https://github.com/ChuMicro/ChuMicro/blob/main/LICENSE)
