# chumicro-workspace

<img src="https://raw.githubusercontent.com/ChuMicro/ChuMicro/main/support/docs/chumicro_tip.png"
align="left" width="64" style="margin-right: 16px; margin-bottom: 8px;">

**Host CLI for ChuMicro project workspaces — onboard a board, write app code, deploy to one or many targets, watch the REPL.**

Wraps `chumicro-deploy` and `chumicro-repl` with the workspace-shaped pieces those packages don't own: a deploy-time config-merge pipeline (gitignored `workspace.yml` + `projects/*/config.toml` → `runtime_config.msgpack`), a CLI that reads `workspace.yml`, three-zone `devices.yml` round-trip, board-state onboarding, firmware URL derivation, and the boot-shim layout that lets a single board host one project without you writing a `code.py`.

<br clear="left">

> Part of the [ChuMicro](https://github.com/ChuMicro/ChuMicro) family — small, focused Python libraries for microcontrollers and laptops. [Browse all workbench tools.](https://github.com/ChuMicro/ChuMicro/tree/main/workbench)
> This is a [workbench tool](https://github.com/ChuMicro/ChuMicro/blob/main/docs/contributing/workbench.md) — runs on your laptop, not on the board.  The on-device side is [`chumicro-config`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/config), which reads the msgpack this package writes.

## Install

```bash
pip install chumicro-workspace
```

`chumicro-deploy` (and its `pyserial` / `mpremote` deps) plus `msgpack` and `ruamel.yaml` come along.  The starter workspace lives at [`ChuMicro/ChuMicro-Workspace-Template`](https://github.com/ChuMicro/ChuMicro-Workspace-Template) — typical bootstrap is `git clone` it (or click "Use this template" on GitHub) then run `python run.py setup`, which creates a venv and installs this package.

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
python run.py deploy my_project --tail 30             # ship + run, then tail for 30 s
python run.py repl                                    # interactive REPL on the active device
```

### How config flows from your edits to the device

The runtime config a project receives at boot is the deep-merge of two gitignored host-side sources, both sharing the same section-namespaced shape:

```
workspace.yml ──────────────────► projects/<name>/config.toml
  (gitignored — workspace-wide       (gitignored when scaffolded by `new`;
   defaults + your credentials        tracked when shipped with the workspace
   in one place; deep-merge           template; per-project knobs — sample
   loser to per-project)              period, mqtt topic, sensor pins)

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

`chumicro-workspace dump-config <project>` prints the merged dict your project would receive without actually deploying — useful when debugging which layer a key landed in.

## What's included

### CLI subcommands

`chumicro-workspace <subcommand>` (or `python run.py <subcommand>` from a workspace).

| Group | Commands |
|---|---|
| **Bootstrap / setup** | `setup`, `update`, `bootstrap` (workspaces are *created* by cloning the template repo, not a command) |
| **Authoring** | `new <path>` (project), `new --library <name>` (chumicro-style library) |
| **Config** | `dump-config <project>`, `config-validate <project>` |
| **Devices** | `add-device`, `probe`, `discover`, `devices`, `remove-device`, `reset-device`, `rename --device` |
| **Deploy / run** | `deploy <project> [--tail SECONDS]`, `deploy-example`, `demo`, `repl [--tail SECONDS]`, `projects [--flat]` |
| **Libraries** | `library list\|add\|update\|remove\|forget\|switch-channel` |
| **Health** | `status`, `doctor` (also runs as a fast pre-deploy gate; `deploy --skip-health-check` opts out) |
| **Quality** | `test`, `lint`, `preflight` (chains lint + test; respects `workspace.yml`'s `quality:` block) |
| **Firmware** | `install-firmware`, `upgrade-firmware`, `reset-board` |

### `libs/` vs `libraries/` — when to use each

Both hold code your projects can `import`.  Pick by *weight*:

| Want to ship… | Drop it under | Imports look like | Notes |
|---|---|---|---|
| A 50-line helper your projects share | `libs/foo.py` | `from libs.foo import bar` | No tests, no version, no scaffolding. |
| A full chumicro-style library you might publish someday | `libraries/<name>/` (via `new --library`) | `import <name>` | Gets `src/`, `tests/`, `docs/`, `examples/`, `pyproject.toml`, `VERSION` — the publishable-library layout. |
| A third-party package | `packages/` (via `sync`) | `import <name>` | Gitignored mirror cache. |

The import-graph search path resolves explicit `library_sources:` overrides → `libs/` → every `libraries/<name>/src/` (auto-discovered) → `packages/`.

### Boot-shim layout

When the project ships `app.py` with a `run()` callable and no `code.py` / `main.py` of its own, `deploy` auto-detects boot-shim mode and ships this on-device shape:

```
/code.py                  # synthesised three-line shim: from app import run; run()
                          # (or /main.py on MicroPython — only the runtime-matching file lands)
/app.py                   # your code — def run(): ...
/runtime_config.msgpack   # merged config (see pipeline above)
/lib/<chumicro_libs>/...  # libraries the project imports (when --import-graph composes)
```

Two responsibilities, one synthesised shim file: deploy owns `/code.py` (or `/main.py`) at the device root and the user owns everything else.  One project per board — switch by redeploying.

When the project ships its own `code.py` / `main.py`, plain mode kicks in and deploy ships project files at the device root verbatim, no shim synthesis.  The runtime-matching filename declares intent: deploying a `code.py`-only project to a MicroPython board (or `main.py`-only to CircuitPython) surfaces as a clear user error before any bytes leave the host.

## Where this fits

Depends on [`chumicro-deploy`](../deploy/) (transport) and [`chumicro-repl`](../repl/) (lazily loaded for `repl` tail/interactive mode and `deploy --tail`).  Top-level umbrella CLI — most users reach for `chumicro-workspace`, not the lower-level tools directly.  The on-device side is [`chumicro-config`](../../libraries/config/), which reads the msgpack this package writes.

## Public Python API

```python
from chumicro_workspace import (
    # Config merge
    build_runtime_config, compose_runtime_config, merge_configs,
    read_workspace_yaml, read_project_config,
    write_runtime_config, WorkspaceConfigError,
    read_workspace_yml_template,

    # Deploy sources
    WithRuntimeConfig, project_directory_source,
    project_boot_source, project_import_graph_source,

    # devices.yml three-zone round-trip
    add_device, update_device_address, update_device_hardware,
    rename_device, set_runtime_default, load_devices, dump_devices,

    # Onboarding
    BoardState, OnboardingDiagnosis, detect_board_state, find_uf2_drive,

    # Firmware URL derivation
    derive_firmware_url, latest_circuitpython_url, latest_micropython_url,
    list_circuitpython_versions, list_micropython_builds,
    micropython_board_for_machine, UnresolvedFirmwareError,

    # Import-graph
    build_search_paths, read_library_sources,

    # Per-project → per-device mapping
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
| [`chumicro-repl`](../repl/) | Interactive + tail serial REPL |
| [`chumicro-pytest-device`](../pytest-device/) | Run tests on real boards via pytest |

## Examples

This package is a CLI tool — there's no "use it in your code" example shape that doesn't just mirror a CLI subcommand.  See the [user guide](docs/guide.md) for end-to-end walkthroughs (config pipeline, deploy modes, library scaffolding, board onboarding) and `chumicro-workspace --help` for the full command surface.

The Python API surface (the `from chumicro_workspace import ...` block above) exists so [`chumicro-deploy`](../deploy/), the workspace template's `run.py` shim, and the [`chumicro-workspace` CLI](src/chumicro_workspace/cli.py) itself can compose against it — not as a "build your own workspace tool" surface.  If you find yourself reaching for it, the CLI probably already exposes what you want; file an issue if it doesn't.

## Contributing

Working on `chumicro-workspace` itself?  Clone the [mono-repo](https://github.com/ChuMicro/ChuMicro) if you haven't already — the rest of the workflow assumes you're inside that workspace.

```bash
pip install -e .[test]
pytest tests/                  # host-side tests
pytest functional_tests/       # on-device tests (needs a board registered in devices.yml)
```

Register a board before running functional tests: `chumicro-workspace add-device <id> --address <port>`.

## Docs

📖 **[Stable docs](https://chumicro.github.io/ChuMicro/workspace/stable/)** · **[Experimental docs](https://chumicro.github.io/ChuMicro/workspace/experimental/)**

## Find this library

- **PyPI:** [chumicro-workspace](https://pypi.org/project/chumicro-workspace/)
- **Source:** [workbench/workspace](https://github.com/ChuMicro/ChuMicro/tree/main/workbench/workspace)
- **Workspace template:** [`ChuMicro/ChuMicro-Workspace-Template`](https://github.com/ChuMicro/ChuMicro-Workspace-Template)

## License

[MIT](https://github.com/ChuMicro/ChuMicro/blob/main/LICENSE)
