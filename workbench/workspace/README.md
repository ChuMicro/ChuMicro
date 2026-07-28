# chumicro-workspace

<img src="https://raw.githubusercontent.com/ChuMicro/ChuMicro/main/support/docs/chumicro_tip.png"
align="left" width="64" style="margin-right: 16px; margin-bottom: 8px;">

**Host CLI for ChuMicro project workspaces: bring up a new board, write a project, ship it, and watch it run.**

One command registers a board you just plugged in.  Another scaffolds a project.  `deploy` sends the project's code and the config it needs to the board and starts it, and `deploy --tail` streams the board's output back to your terminal while it runs.  Your wifi password lives in one file you keep out of git, and the board receives a merged copy at deploy time instead of a hard-coded string in your source.

<br clear="left">

> Part of the [ChuMicro](https://github.com/ChuMicro/ChuMicro) family, small focused Python libraries for microcontrollers and laptops. [Browse all workbench tools.](https://github.com/ChuMicro/ChuMicro/tree/main/workbench)
> This is a [workbench tool](https://github.com/ChuMicro/ChuMicro/blob/main/docs/contributing/workbench.md): it runs on your laptop, not on the board.  The on-device side is [`chumicro-config`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/config), which reads the msgpack this package writes.

## Install

```bash
pip install chumicro-workspace
```

`chumicro-deploy` comes along with its `pyserial` and `mpremote` dependencies, plus `msgpack`, `ruamel.yaml`, and `tomlkit`.  `chumicro-repl` is optional and loaded only when you use it: install it to get the interactive `repl` command and `deploy --tail`.

The starter workspace lives at [`ChuMicro/ChuMicro-Workspace-Template`](https://github.com/ChuMicro/ChuMicro-Workspace-Template).  Typical day-zero is to `git clone` it (or click "Use this template" on GitHub) and run `python run.py setup`, which creates a venv and installs this package.

<details>
<summary>Experimental (pre-release) versions and channel switching</summary>

Pre-release builds publish automatically when the package version is bumped.

```bash
pip install chumicro-workspace-experimental
```

</details>

## Quick example

The workspace template ships a `run.py` shim that forwards to `chumicro-workspace`, so both spellings work:

```bash
# Inside a freshly cloned workspace:
python run.py setup                                   # one-time bootstrap
python run.py bootstrap back-porch --address /dev/cu.usbmodem1101
# (probes the runtime, registers the board in devices.yml, and prints
#  what to run next.  Add --demo to also ship the built-in demo payload.)

# Then iterate:
python run.py new my_project                          # scaffold from projects/_template/
python run.py deploy my_project                       # ship + run on the active device
python run.py deploy my_project --tail 30             # ship + run, then tail for 30 s
python run.py repl                                    # interactive REPL on the active device
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

`chumicro-workspace dump-config <project>` prints the merged dict your project would receive without deploying anything, which is the fastest way to find out which file a key came from.

## What's included

### CLI subcommands

`chumicro-workspace <subcommand>` (or `python run.py <subcommand>` from a workspace).

| Group | Commands |
|---|---|
| **Bootstrap / setup** | `setup`, `update`, `bootstrap` (workspaces are *created* by cloning the template repo, not by a command) |
| **Authoring** | `new <path>` (project), `new <name> --library` (chumicro-style library), `new <name> --workbench` (host-only tool) |
| **Config** | `dump-config <project>`, `config-validate <project>` |
| **Devices** | `add-device`, `probe`, `discover`, `devices`, `remove-device`, `reset-device`, `rename --device` |
| **Deploy / run** | `deploy <project> [--tail SECONDS]`, `deploy-example`, `demo`, `repl [--tail SECONDS]`, `projects [--flat]` |
| **Libraries** | `library list\|browse\|add\|update\|remove\|forget\|switch-channel` |
| **Health** | `status`, `doctor` (also runs as a fast pre-deploy gate; `deploy --skip-health-check` opts out) |
| **Quality** | `test`, `lint`, `preflight` (chains lint + test; respects the `quality:` knobs) |
| **Firmware** | `install-firmware`, `upgrade-firmware`, `reset-board` |

Every device command rewrites `devices.yml` in place, keeping your comments and field order.  Three zones decide who wins a conflict: user-owned fields (`id`, `description`, `deploy_mode`) are never overwritten, probed-always fields (`address`, `firmware_version`) refresh on each probe, and hardware-once fields (`runtime` and the `hardware:` block) need an explicit `--force`, because a changed uid usually means you swapped boards.

### `shared/` vs `libraries/`: when to use each

Both hold code your projects can `import`.  Pick by weight:

| Want to ship… | Drop it under | Imports look like | Notes |
|---|---|---|---|
| A 50-line helper your projects share | `shared/foo.py` | `from foo import bar` | No tests, no version, no scaffolding.  The search path roots at `shared/` itself, so there is no `shared.` prefix to qualify against. |
| A full chumicro-style library you might publish someday | `libraries/<name>/` (via `new <name> --library`) | `import <name>` | Gets `src/`, `tests/`, `docs/`, `examples/`, `pyproject.toml`, and `VERSION`: the publishable-library layout. |
| A published chumicro library | `libraries/<name>/` (via `library add <name>`) | `import chumicro_<name>` | Fetched from the release channel along with the chumicro libraries it imports.  A re-fetch backs up a tree you have edited instead of clobbering it. |
| A third-party module you vendor yourself | `packages/` | `import <name>` | Nothing populates this for you.  Drop files in and the search path finds them last. |

The import-graph search path resolves explicit `library_sources:` overrides first, then `shared/`, then every `libraries/<name>/src/` (auto-discovered), then `packages/`.

### Boot-shim layout

When a project ships `app.py` with a top-level `run()` and no `code.py` / `main.py` of its own, `deploy` picks the boot-shim layout automatically and ships this on-device shape:

```
/code.py                  # synthesised shim: from app import run as _run; _run()
                          # (or /main.py on MicroPython; only the runtime-matching
                          #  file is written, never both)
/app.py                   # your code: def run(): ...
/runtime_config.msgpack   # merged config (see the pipeline above)
/lib/<chumicro_libs>/...  # libraries the project imports (when --import-graph composes)
```

Deploy owns the entrypoint file at the device root and you own everything else.  One project per board: to change which project runs, deploy the other one.

When a project ships its own `code.py` / `main.py`, deploy uses plain mode instead and copies the project's files to the device root verbatim, synthesising nothing.  The filename declares which runtime the project targets, so deploying a `code.py`-only project to a MicroPython board (or a `main.py`-only project to CircuitPython) fails with a clear message before any bytes leave the host.

## Where this fits

This package builds on [`chumicro-deploy`](https://github.com/ChuMicro/ChuMicro/tree/main/workbench/deploy), which owns the serial and USB transports, the firmware flashing flow, and the `devices.yml` schema.  [`chumicro-repl`](https://github.com/ChuMicro/ChuMicro/tree/main/workbench/repl) is optional and imported only when you reach for `repl` or `deploy --tail`.  Most people use `chumicro-workspace` and never call the lower-level tools directly.  The on-device counterpart is [`chumicro-config`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/config), which reads the msgpack this package writes.

## Public Python API

The package root keeps a deliberately narrow surface:

```python
from chumicro_workspace import (
    WorkspaceLayout,              # find the workspace root, resolve project paths
    WorkspaceNotFoundError,       # raised when no workspace.yml sits above cwd
    ProjectClassification,        # how a projects/ subdirectory was classified
    compose_runtime_config,       # the merged config as a dict, nothing written
    read_workspace_yml_template,  # starter workspace.yml content
    read_devices_yml_template,    # starter devices.yml content
    verify_examples,              # AST check that a library's examples import cleanly
)
```

Everything else lives in a submodule and is imported by its real path:

```python
from chumicro_workspace.pipeline import build_runtime_config
from chumicro_workspace.deploy_source import WithRuntimeConfig, project_directory_source
from chumicro_workspace.boot_shim import SHIM_ENTRYPOINT_SOURCE, project_boot_source
from chumicro_workspace.import_graph import build_search_paths, project_import_graph_source
from chumicro_workspace.onboarding import BoardState, detect_board_state
from chumicro_workspace.firmware_support import check_firmware_supported
from chumicro_workspace.health import collect_health_findings
from chumicro_workspace.quality import load_quality_config
from chumicro_workspace.recovery import detect_hints
from chumicro_workspace.scaffold import scaffold_library
```

Reading and writing `devices.yml` lives in `chumicro-deploy`, which owns the file's schema:

```python
from chumicro_deploy.config.devices_yaml import (
    add_device,
    dump_devices,
    load_devices,
    update_device_address,
)
```

## Companions

| Workbench tool | Why you'd use it alongside |
|---|---|
| [`chumicro-deploy`](https://github.com/ChuMicro/ChuMicro/tree/main/workbench/deploy) | Lower-level transport and flashing.  Workspace composes on top |
| [`chumicro-repl`](https://github.com/ChuMicro/ChuMicro/tree/main/workbench/repl) | Interactive and tail serial REPL |
| [`chumicro-pytest-device`](https://github.com/ChuMicro/ChuMicro/tree/main/workbench/pytest-device) | Run tests on real boards via pytest |

## Examples

This package is a CLI tool, so there is no "use it in your code" example that isn't just a CLI subcommand in Python clothing.  See the [user guide](https://chumicro.github.io/ChuMicro/workspace/stable/guide/) for end-to-end walkthroughs (the config pipeline, deploy layouts, library scaffolding, board onboarding) and `chumicro-workspace --help` for the full command surface.

The Python API exists so the [`chumicro-workspace` CLI](https://github.com/ChuMicro/ChuMicro/tree/main/workbench/workspace/src/chumicro_workspace/cli/) and the workspace template's `run.py` shim can compose against it, not as a "build your own workspace tool" surface.  If you find yourself reaching for it, the CLI probably already does what you want; file an issue if it doesn't.

## Contributing

Issues, bug reports, and pull requests are welcome, and so is "I ran it on this board and here's what happened", some of the most useful feedback a hardware project can get.  Development happens in the [ChuMicro repository](https://github.com/ChuMicro/ChuMicro), whose contributing guide covers setup and the test workflow.

## Docs

📖 **[Stable docs](https://chumicro.github.io/ChuMicro/workspace/stable/)** · **[Experimental docs](https://chumicro.github.io/ChuMicro/workspace/experimental/)**

## Find this library

- **PyPI:** [chumicro-workspace](https://pypi.org/project/chumicro-workspace/)
- **Source:** [workbench/workspace](https://github.com/ChuMicro/ChuMicro/tree/main/workbench/workspace)
- **Workspace template:** [`ChuMicro/ChuMicro-Workspace-Template`](https://github.com/ChuMicro/ChuMicro-Workspace-Template)

## License

[MIT](https://github.com/ChuMicro/ChuMicro/blob/main/LICENSE)
