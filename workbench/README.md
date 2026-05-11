# ChuMicro workbench tools

Host-side tools that run on your laptop and help you manage connected boards.  CPython-only, ship to PyPI, never reach the device.

> Looking for the front door?  → [`/README.md`](../README.md) — the 8-line demo, install, and "now what?" doors.
>
> Looking for device libraries?  → [`/libraries/`](../libraries/) — the cross-runtime libraries that run on the board.

These tools are **optional** — you can use the [device libraries](../libraries/) without them.  Reach for workbench when you want one-command deploy + REPL workflows, project workspaces, or hardware-gated test integration.

## What's in the box?

| Tool | What it does |
|---|---|
| **[deploy](deploy/)** | Push code onto a CircuitPython or MicroPython board, probe its identity, and flash firmware (UF2 or esptool).  Programmatic API + `chumicro-deploy` CLI; recovery layer that classifies failures and walks you through fixes. |
| **[repl](repl/)** | Serial REPL with traceback highlighting, an `mpremote`-compatible TUI, a `tail()` follow-mode for deploy orchestration, and a programmatic `ReplSession` for headless test fixtures.  `chumicro-repl` CLI. |
| **[workspace](workspace/)** | One-stop host CLI + Python API for ChuMicro project workspaces — `init` (clone a starter), `setup` (bootstrap a venv), `add-device`, `deploy` (single project, `--all-devices`, or `--all-projects`), `repl <project>` (deploy-then-tail), `install-firmware`, `status` / `doctor` health checks, `new --library` / `new --from`, path-aware `rename`, `update` (re-flow tool-owned template files).  Canonical starter lives at [`ChuMicro-Workspace-Template`](https://github.com/ChuMicro/ChuMicro-Workspace-Template). |
| **[pytest-device](pytest-device/)** | Pytest plugin that intercepts collection under any `functional_tests/` directory, stages your library + test source onto a connected CP / MP board via `chumicro-deploy`, runs the test in the device runtime, and surfaces the on-device outcome to host-side pytest.  Auto-registers via `pytest11`; reads `devices.yml`. |

## Install

Workbench packages live on PyPI only — no bundle, no `.mpy` step, just pip:

```bash
pip install chumicro-workspace        # the front door — wraps deploy + repl + project layout
pip install chumicro-deploy           # if you only need the deploy primitive
pip install chumicro-repl             # if you only need the REPL helper
pip install chumicro-pytest-device    # pytest plugin
```

`chumicro-workspace` already depends on `chumicro-deploy` and `chumicro-repl`, so installing the workspace package brings the whole host-side stack in one command.

For the experimental channel see [`INSTALL.md`](../INSTALL.md).

## When to reach for workbench

- **"I want a real project layout"** → [ChuMicro-Workspace-Template](https://github.com/ChuMicro/ChuMicro-Workspace-Template) + [workspace](workspace/) — clone-and-go, no live-on-device editing.
- **"I want one command to push code to my board"** → [deploy](deploy/) — handles RAM-mode (mount + execute) and flash-mode (atomic rsync) without you having to think about it.
- **"I want to watch my board's REPL after a deploy"** → [repl](repl/) (or `python run.py repl <project>` from a workspace, which composes deploy + repl).
- **"I want my pytest functional tests to run on real hardware"** → [pytest-device](pytest-device/) — register a board in `devices.yml`, the plugin handles the rest.
