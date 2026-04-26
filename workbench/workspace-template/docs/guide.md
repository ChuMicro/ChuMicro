# Guide

`chumicro-workspace-template` scaffolds a fresh ChuMicro project workspace and pushes template improvements over time without touching the user-owned files.

## Init

```bash
chumicro-workspace-template init my-house
```

Lays down the canonical workspace shape under `my-house/`:

```
my-house/
├── workspace.yml          # defaults that things inherit
├── devices.yml            # board registry (three-zone, comments preserved)
├── secrets.yml.example    # copy to secrets.yml + fill in
├── pyproject.toml         # pins chumicro-workspace-runtime
├── run.py                 # `python run.py <cmd>` shim
├── AGENTS.md              # workspace conventions for AI agents
├── README.md              # starter README — yours to edit
├── .gitignore
├── things/
│   └── _template/         # `python run.py new` copies from here
│       ├── config.toml
│       └── app.py
├── libs/
│   └── .gitkeep
└── packages/
    └── .gitignore
```

If `my-house/` already exists, `init` writes only the missing files (it skips conflicts and reports them).  Pass `--force` to overwrite everything.

Use `--from <path>` to scaffold from a custom template (local path; future: git URL).  The same three-zone classification applies, so the custom template just needs to follow the same file layout.

## Update

```bash
cd my-house
chumicro-workspace-template update
```

`update` refreshes the **tool-owned** slice only — `run.py`, `AGENTS.md`, `pyproject.toml`, `things/_template/`.  Everything else is left alone:

- **User-owned** (`workspace.yml`, `devices.yml`, `secrets.yml`, `libs/`, `packages/`, `things/<your-things>/`) — never touched.
- **Init-only** (`.gitignore`, `secrets.yml.example`, `README.md`) — written on `init` if absent, skipped on `update` so user edits survive.

This means: the `chumicro-workspace-runtime` version pin in `pyproject.toml` flows in, the `run.py` shim stays in sync with new dispatcher commands, and template improvements to `things/_template/` lift the bar for future things — but you never lose your config edits or your existing things.

## Programmatic API

```python
from pathlib import Path
from chumicro_workspace_template import (
    init, update, default_template_root, classify, Zone,
)

# Lay down a fresh workspace.
report = init(Path("my-house"))
assert report.count("written") > 0

# Update the tool-owned slice.
report = update(Path("my-house"))
for path, action in report:
    print(f"{action:>10}  {path}")

# Inspect the built-in template.
print(default_template_root())

# Classify a file path manually.
assert classify("things/_template/app.py") is Zone.TOOL_OWNED
assert classify("things/back-porch/app.py") is Zone.USER_OWNED
```

## Three-zone model

Decision 0029 §9 introduced three zones for `devices.yml`; this package generalizes them across the entire workspace.  See [`chumicro_workspace_template.manifest`](api.md) for the path-to-zone classifier and the lists of canonical paths in each zone.

## Workbench-only

This package runs on CPython only — never on a microcontroller.  See [Decision 0032](https://github.com/ChuMicro/ChuMicro/blob/main/plans/decisions/0032-workbench-host-tools.md) for the workbench-package pattern.
