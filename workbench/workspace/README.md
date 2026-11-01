# chumicro-workspace

<img src="https://raw.githubusercontent.com/ChuMicro/ChuMicro/main/support/docs/chumicro_tip.png"
align="left" width="64" style="margin-right: 16px; margin-bottom: 8px;">

**The laptop command that puts your Python project on a CircuitPython or MicroPython board and shows what the board prints.**

`chumicro-workspace` registers each board you plug in, creates a folder for each project, copies a project and every library it imports onto the board, and streams the board's output back to your terminal.  It works with any CircuitPython or MicroPython board, whether or not your code uses ChuMicro libraries.  Your WiFi password stays in a `secrets.toml` file on your laptop, and each deploy carries it to the board.

<br clear="left">

> Part of the [ChuMicro](https://github.com/ChuMicro/ChuMicro) family, small focused Python libraries for microcontrollers and laptops. [Browse all workbench tools.](https://github.com/ChuMicro/ChuMicro/tree/main/workbench)
> This is a [workbench tool](https://github.com/ChuMicro/ChuMicro/blob/main/docs/contributing/workbench.md): it runs on your laptop, not on the board.  The board-side half is [`chumicro-config`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/config), which reads the settings file each deploy writes.

## First five commands

Run these in a workspace made from the [workbench template](https://github.com/ChuMicro/ChuMicro-Workbench-Template), in this order:

```bash
python3 run.py bootstrap                     # register the board plugged into USB
python3 run.py new blinker                   # create projects/blinker/ with an app.py for your code
python3 run.py library add chumicro_timing   # fetch a library into the workspace's libraries/
python3 run.py deploy blinker --tail 30      # copy the project onto the board, show 30 s of output
python3 run.py repl                          # open the board's Python prompt; Ctrl-X leaves
```

The template's `run.py` starts `chumicro-workspace` from the workspace's own virtual environment, so `python3 run.py deploy` and `chumicro-workspace deploy` are the same command.  In a clone of the ChuMicro repository, or after `pip install chumicro-workspace`, type `chumicro-workspace` in place of `python3 run.py`.

[Start here](https://chumicro.com/ChuMicro/guides/start-here/) walks these commands with a blink program, from a board in its packaging to the board on your WiFi.  The [guide](https://chumicro.com/ChuMicro/workspace/stable/guide/) covers each command in depth.

## Install

Most people get `chumicro-workspace` with the workbench template:

```bash
git clone --depth 1 https://github.com/ChuMicro/ChuMicro-Workbench-Template my-workspace
cd my-workspace
python3 run.py setup      # creates a virtual environment and installs the tools
```

On its own, from PyPI:

```bash
pip install chumicro-workspace
```

`chumicro-deploy` comes along with `pyserial` and `mpremote`, plus `msgpack`, `ruamel.yaml`, and `tomlkit`.  The `repl` command and `deploy --tail` also need `chumicro-repl`, which the template installs and `pip install chumicro-repl` adds.

<details>
<summary>Experimental (pre-release) versions and channel switching</summary>

Pre-release builds publish automatically when the package version is bumped.

```bash
pip install chumicro-workspace-experimental
```

</details>

## Every command

`chumicro-workspace <command> --help` describes each one, and `python3 run.py <command> --help` does the same in a workspace.

| Group | Commands | What they do |
|---|---|---|
| First steps | `setup`, `bootstrap`, `demo` | Install the tools, register a board, send it a counting program |
| Projects | `new <name>`, `projects`, `rename --project` | Create, list, and rename projects under `projects/`.  `new <name> --library` creates a library of your own |
| Run code on a board | `deploy <name>`, `deploy-example <library> <example>`, `repl` | Copy code onto a board, watch its output, type at its prompt |
| Libraries | `library list\|browse\|add\|update\|remove\|forget\|switch-channel` | Fetch ChuMicro libraries into `libraries/` and keep them current |
| Boards | `add-device`, `discover`, `devices`, `probe`, `rename --device`, `remove-device`, `reset-device` | Find, register, and manage the boards in `devices.yml` |
| Settings | `dump-config <name>`, `config-validate` | Show and check the settings each project receives from `secrets.toml` and `project_config.toml` |
| Firmware | `install-firmware`, `upgrade-firmware`, `reset-board` | Flash a newer CircuitPython or MicroPython, or erase a board's files |
| Health | `status`, `doctor` | Check the workspace files, the Python version, and the serial ports |
| Code checks | `test`, `lint`, `preflight` | Run pytest, ruff, and `chumicro-checks` over the workspace |
| Upkeep | `update` | Refresh the files the workbench template provides |

## Where this fits

`chumicro-workspace` runs on [`chumicro-deploy`](https://github.com/ChuMicro/ChuMicro/tree/main/workbench/deploy), which talks to the board over USB, flashes firmware, and owns the `devices.yml` format.  The `repl` command and `deploy --tail` use [`chumicro-repl`](https://github.com/ChuMicro/ChuMicro/tree/main/workbench/repl).  [`chumicro-pytest-device`](https://github.com/ChuMicro/ChuMicro/tree/main/workbench/pytest-device) runs tests on a connected board.  On the board, [`chumicro-config`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/config) reads the settings each deploy writes.

## Python API

The CLI is built on these names, and a script can import them too:

```python
from chumicro_workspace import (
    WorkspaceLayout,              # find the workspace folder, resolve project paths
    WorkspaceNotFoundError,       # raised when no workspace.yml sits above the current folder
    ProjectClassification,        # a projects/ folder's kind: project, namespace, or supporting
    compose_runtime_config,       # the merged settings as a dict, nothing written
    read_workspace_yml_template,  # starter workspace.yml text
    read_devices_yml_template,    # starter devices.yml text
    verify_examples,              # checks that a library's examples import cleanly
)
```

The [API reference](https://chumicro.com/ChuMicro/workspace/stable/api/) documents these and the submodules behind each command, such as `chumicro_workspace.pipeline` for the settings merge and `chumicro_workspace.boot_shim` for the generated `code.py`.

## Contributing

Issues, bug reports, and pull requests are welcome, and so is "I ran it on this board and here's what happened", some of the most useful feedback a hardware project can get.  Development happens in the [ChuMicro repository](https://github.com/ChuMicro/ChuMicro), whose contributing guide covers setup and the test workflow.

## Docs

📖 **[Stable docs](https://chumicro.com/ChuMicro/workspace/stable/)** · **[Experimental docs](https://chumicro.com/ChuMicro/workspace/experimental/)**

## Find this library

- **PyPI:** [chumicro-workspace](https://pypi.org/project/chumicro-workspace/)
- **Source:** [workbench/workspace](https://github.com/ChuMicro/ChuMicro/tree/main/workbench/workspace)
- **Workspace template:** [`ChuMicro/ChuMicro-Workbench-Template`](https://github.com/ChuMicro/ChuMicro-Workbench-Template)

## License

[MIT](https://github.com/ChuMicro/ChuMicro/blob/main/LICENSE)
