# chumicro-workspace

<img src="https://raw.githubusercontent.com/ChuMicro/ChuMicro/main/support/docs/chumicro_tip.png" align="left" width="64" style="margin-right: 16px; margin-bottom: 8px;">

**One-stop host CLI for ChuMicro project workspaces — onboard a board, write app code, deploy to one or many targets, watch the REPL.**

Wraps `chumicro-deploy` and `chumicro-repl` with the workspace-shaped pieces those packages don't own: a deploy-time config-merge pipeline (`workspace.yml` + `projects/*/config.toml` + `secrets.yml` → `runtime_config.msgpack`), a CLI that reads `workspace.yml`, three-zone `devices.yml` round-trip, board-state onboarding, firmware URL derivation, and the boot-shim layout that lets a single board host one project without you writing a `code.py`.

<br clear="left">

> Part of the [ChuMicro](https://github.com/ChuMicro/ChuMicro) family — small, focused Python libraries for microcontrollers and laptops. [See all libraries.](https://github.com/ChuMicro/ChuMicro#whats-in-the-box)
> This is a [workbench tool](https://github.com/ChuMicro/ChuMicro/blob/main/docs/contributing/workbench.md) — runs on your laptop, not on the board.  The on-device side is [`chumicro-config`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/config), which reads the msgpack this package writes.

## Installation

```bash
pip install chumicro-workspace
```

`chumicro-deploy` (and its `pyserial` / `mpremote` deps) plus `msgpack` and `ruamel.yaml` come along.  The canonical workspace template lives at [`ChuMicro/ChuMicro-Workspace-Template`](https://github.com/ChuMicro/ChuMicro-Workspace-Template) — typical bootstrap is `git clone` it (or click "Use this template" on GitHub) then run `python run.py setup`, which creates a venv and installs this package.

<details>
<summary>Experimental (pre-release) versions and channel switching</summary>

Pre-release builds publish automatically when the package version is bumped.

```bash
pip install chumicro-workspace-experimental
```

</details>

## Quick example

The workspace template ships a `run.py` shim that forwards to `chumicro-workspace` — typical day-zero is:

```bash
# Inside a freshly cloned workspace:
python run.py setup                                 # one-time bootstrap
python run.py bootstrap --port /dev/cu.usbmodem1101 --device-id back-porch
# (the wizard probes the runtime, registers the device, deploys
# the built-in demo payload — pass --no-demo to skip the demo step.)

# Then iterate:
python run.py new my_project                          # scaffold from projects/_template/
python run.py deploy my_project                       # ship + run on the active device
python run.py repl my_project --tail 30               # deploy + tail for 30 s
```

### How config flows from your edits to the device

The runtime config a project receives at boot is the merge of three host-side sources, with secret references resolved at deploy time:

```
secrets.yml                workspace.yml              projects/<name>/config.toml
   (host)                     (host)                          (host)
      │                          │                              │
      └──────────────┬───────────┴──────────────────────────────┘
                     ▼
                 merge_configs                  ← chumicro_workspace.merge
                     │                              (deep per-key merge: project
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

`chumicro-workspace dump-config <project>` prints the merged dict your project would receive without actually deploying — useful when debugging which config section a key landed in or whether a `!secret` resolved to what you expected.

## What's included

### CLI subcommands

`chumicro-workspace <subcommand>` (or `python run.py <subcommand>` from a workspace).

| Group | Commands |
|---|---|
| **Bootstrap / setup** | `init`, `setup`, `update`, `bootstrap` |
| **Authoring** | `new <path>` (project), `new --library <name>` (chumicro-style library), `dump-config <project>` |
| **Devices** | `add-device`, `probe`, `discover`, `devices`, `rename --device` |
| **Deploy / run** | `deploy <project>`, `demo`, `repl [<project>] [--tail SECONDS]`, `projects [--flat]` |
| **Health** | `status`, `doctor` (also runs as a fast pre-deploy gate; `deploy --skip-health-check` opts out) |
| **Quality** | `test`, `lint`, `preflight` (chains lint + test; respects `workspace.yml`'s `quality:` block) |
| **Firmware** | `install-firmware`, `upgrade-firmware` |
| **Stubs** | `sim`, `env`, `use`, `sync`, `upgrade` (planned / deprecated — print a "not yet" message) |

### `libs/` vs `libraries/` — when to use each

Both hold code your projects can `import`.  Pick by *weight*:

| Want to ship… | Drop it under | Imports look like | Notes |
|---|---|---|---|
| A 50-line helper your projects share | `libs/foo.py` | `from libs.foo import bar` | No tests, no version, no scaffolding. |
| A full chumicro-style library you might publish someday | `libraries/<name>/` (via `new --library`) | `import <name>` | Gets `src/`, `tests/`, `docs/`, `examples/`, `pyproject.toml`, `VERSION` — same shape the chumicro mono-repo uses. |
| A third-party package | `packages/` (via `sync`) | `import <name>` | Gitignored mirror cache. |

The import-graph search path resolves explicit `library_sources:` overrides → `libs/` → every `libraries/<name>/src/` (auto-discovered) → `packages/`.

### Boot-shim layout

`deploy --boot-shim <name>` ships the [Decision 0029 §3](https://github.com/ChuMicro/ChuMicro/blob/main/plans/decisions/0029-project-workspace.md) on-device shape:

```
/code.py                              # two-line shim: import workspace_runtime; boot()
/active.py                            # PROJECT_NAME = "garage.sensors.door_open"
/runtime_config.msgpack               # merged config (see pipeline above)
/lib/workspace_runtime/__init__.py    # boot module — imports projects.<dotted>.app and calls run()
/lib/projects/__init__.py               # package marker
/lib/projects/garage/__init__.py        # one per nested namespace level
/lib/projects/garage/sensors/door_open/ # the project's files
    __init__.py
    app.py                            # def run(): ...  ← your code
```

Three layers, three responsibilities: `code.py` is the firmware entrypoint (stable across deploys), `active.py` names which project is current (regenerated per deploy), `app.py` is your code (lives inside the project dir).  None of these names is a CircuitPython convention except `code.py` itself — `app.py` is workspace's name for "the project's entrypoint module exporting `run()`".

### Status

> Project-workspace Phase 4a feature-complete + workspace-ecosystem Phases 1, 2, 4, 5 shipped (2026-04-27); Phase 2f closed 2026-05-01.  The package consolidates everything Decision 0029 / 0035 / 0038 specified plus the user-friendliness pass that followed: nested project namespaces, an `examples/` folder for read-and-scaffold demos, `status` / `doctor` health snapshots (now also a pre-deploy gate), `deploy --dry-run`, `deploy --all-devices`, `deploy --all-projects` + per-project `deploy_targets:` defaults, `repl <project>` one-shot deploy + tail, app-level deploy-failure recovery hints, `new --library` for chumicro-style libraries, `workspace.yml` `quality:` knob wiring, `preflight` + `dump-config` commands.

## Public Python API

```python
from chumicro_workspace import (
    # Config merge (Decision 0035)
    build_runtime_config, merge_configs, resolve_secrets,
    read_workspace_yaml, read_project_config, read_secrets_yaml,
    write_runtime_config, UnresolvedSecretError, WorkspaceConfigError,

    # Deploy sources
    WithRuntimeConfig, project_directory_source,
    project_boot_source, project_import_graph_source,

    # devices.yml three-zone round-trip (Decision 0029 §9)
    add_device, update_device_address, update_device_hardware,
    rename_device, set_runtime_default, load_devices, dump_devices,

    # Onboarding (Decision 0029 §4)
    BoardState, OnboardingDiagnosis, detect_board_state, find_uf2_drive,

    # Firmware URL derivation (Decision 0029 §5)
    derive_firmware_url, latest_circuitpython_url, latest_micropython_url,
    list_circuitpython_versions, list_micropython_builds,
    micropython_board_for_machine, UnresolvedFirmwareError,

    # Import-graph (Decision 0029 §6+§7)
    build_search_paths, read_library_sources,

    # Per-project → per-device mapping (Phase 2f)
    read_deploy_targets,

    # Constants
    RUNTIME_CONFIG_DEVICE_PATH, GENERATED_DIRNAME,
    BOOT_MODULE_DEVICE_PATH, PROJECTS_PACKAGE_INIT_DEVICE_PATH,
    SHIM_ENTRYPOINT_SOURCE,
)
```

Plus `chumicro_workspace.workspace.WorkspaceLayout`, `chumicro_workspace.health.*`, `chumicro_workspace.recovery.*`, `chumicro_workspace.scaffold.*`, and `chumicro_workspace.quality.*` for the workspace-ecosystem add-ons.

## Companions

| Workbench tool | Why you'd use it alongside |
|---|---|
| [`chumicro-deploy`](../deploy/) | Lower-level transport + flashing.  Workspace composes on top |
| [`chumicro-repl`](../repl/) | Interactive + tail-after-deploy serial REPL |
| [`chumicro-pytest-device`](../pytest-device/) | Run tests on real boards via pytest |

## Examples

This package is a CLI tool — there's no "use it in your code" example shape that doesn't just mirror a CLI subcommand.  See the [user guide](docs/guide.md) for end-to-end walkthroughs (config pipeline, deploy modes, library scaffolding, board onboarding) and `chumicro-workspace --help` for the full command surface.

The Python API surface (the `from chumicro_workspace import ...` block above) exists so [`chumicro-deploy`](../deploy/), the workspace template's `run.py` shim, and the [`chumicro-workspace` CLI](src/chumicro_workspace/cli.py) itself can compose against it — not as a "build your own workspace tool" surface.  If you find yourself reaching for it, the CLI probably already exposes what you want; file an issue if it doesn't.

## Developing this library

```bash
python scripts/run.py test --libraries workspace
python scripts/run.py test-workbench-functional --workbench workspace
```

Functional tests need a real board and `devices.yml` populated — `python scripts/run.py setup` materializes the local config files.

## Docs

📖 **[Stable docs](https://chumicro.github.io/ChuMicro/workspace/stable/)** · **[Experimental docs](https://chumicro.github.io/ChuMicro/workspace/experimental/)**

## Find this library

- **PyPI:** [chumicro-workspace](https://pypi.org/project/chumicro-workspace/)
- **Source:** [workbench/workspace](https://github.com/ChuMicro/ChuMicro/tree/main/workbench/workspace)
- **Workspace template:** [`ChuMicro/ChuMicro-Workspace-Template`](https://github.com/ChuMicro/ChuMicro-Workspace-Template)

## License

[MIT](https://github.com/ChuMicro/ChuMicro/blob/main/LICENSE)
