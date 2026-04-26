# AGENTS.md — workspace conventions

This file is for AI coding agents working inside this workspace.  Tool-owned:
`chumicro-workspace-template update` will rewrite it.

## What this is

A ChuMicro project workspace — `things/` are individual deployable apps,
`devices.yml` registers boards, and `python run.py <cmd>` dispatches to
`chumicro-workspace-runtime`.  See the package's
[guide](https://github.com/ChuMicro/ChuMicro/blob/main/workbench/workspace-runtime/docs/guide.md)
for the workflow primer.

## Day-to-day commands

| Command | Purpose |
|---|---|
| `python run.py setup` | One-time: editable-install the workspace's deps. |
| `python run.py new <name>` | Scaffold a new thing under `things/<name>/`. |
| `python run.py add-device <id> --address <port> --runtime <cp\|mp>` | Probe + register a board. |
| `python run.py deploy <thing>` | Ship a thing to the default board. |
| `python run.py deploy <a> <b> <c> --boot-shim --active <a>` | Multi-thing deploy. |
| `python run.py switch <thing>` | Re-point /active.py without re-flashing. |
| `python run.py repl` | Open an interactive REPL on the board. |
| `python run.py install-firmware --method uf2` | Auto-derived firmware download + flash. |

## File ownership

| File | Touch? |
|---|---|
| `things/<your-name>/` | YES — your code. |
| `devices.yml` | YES (or via `add-device`) — three-zone, comments preserved. |
| `secrets.yml` | YES — gitignored, never committed. |
| `workspace.yml` | YES — wider-scope defaults. |
| `libs/`, `packages/` | YES (for `libs/`); leave `packages/` alone. |
| `things/_template/` | NO — copied from template. |
| `run.py`, `AGENTS.md`, `pyproject.toml` | NO — tool-owned, overwritten by `update`. |

## Rules of thumb

- Things must export `def run(): ...` (or define `code.py` / `main.py`
  that block) — the runtime's `boot()` calls it.
- Keep credentials in `secrets.yml` and reference via `!secret <name>`
  from any `config.toml`.
- Run `python run.py test` (forwards to `pytest`) before shipping.
