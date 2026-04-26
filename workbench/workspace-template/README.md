# chumicro-workspace-template

Scaffold + update tool for ChuMicro project workspaces.  Works the way Copier does: an initial `init` lays down a starter tree (`workspace.yml`, `devices.yml`, `things/_template/`, `pyproject.toml`, `run.py` shim, etc.); a later `update` re-applies the *tool-owned* slice of the template over an existing workspace without clobbering the user-owned files (your `things/`, your `secrets.yml`, your `devices.yml`, your `libs/`).

Part of the [ChuMicro](https://github.com/ChuMicro/ChuMicro) workspace.  Workbench tool — runs on your laptop only.  See [Decision 0029](https://github.com/ChuMicro/ChuMicro/blob/main/plans/decisions/0029-project-workspace.md) for the workspace contract this package scaffolds and [Decision 0032](https://github.com/ChuMicro/ChuMicro/blob/main/plans/decisions/0032-workbench-host-tools.md) for the workbench-package pattern.

## Status

Phase 4b minimum-viable.  Ships a built-in default template (the canonical workspace shape); a `--from <local-path>` override is supported, and the future companion repo (Phase 4c) plugs in via the same flag.  `init` and `update` are wired; an interactive merge for tool-owned files that diverged is a follow-on.

## Install

```bash
pip install chumicro-workspace-template
```

## Use

```bash
# Create a new workspace with the built-in default template.
chumicro-workspace-template init my-house

# Or apply a custom template (local path, soon: git URL).
chumicro-workspace-template init my-house --from ./my-template

# Bootstrap the workspace's Python deps + drop into it.
cd my-house
python run.py setup

# Later — pull template improvements without touching your things/.
chumicro-workspace-template update
```

## Three-zone update model

`init` lays down everything.  `update` only rewrites the *tool-owned* zone:

| Zone | Files | `init` | `update` |
|---|---|---|---|
| Tool-owned | `run.py`, `AGENTS.md`, `things/_template/`, `pyproject.toml` (workspace-runtime version pin) | Written | **Rewritten** (template wins) |
| User-owned | `things/<your-things>/`, `secrets.yml`, `devices.yml`, `libs/`, `workspace.yml` | Written if absent | **Never touched** |
| Init-only | `.gitignore`, `secrets.yml.example`, `README.md` | Written if absent | Skipped (preserve user edits) |

The classification lives in `chumicro_workspace_template.manifest`; consult it from your own template-aware tooling if you build one.

## Public Python API

```python
from pathlib import Path
from chumicro_workspace_template import init, update, default_template_root

# Create a workspace from the built-in template.
init(Path("my-house"))

# Or from a custom local path.
init(Path("my-house"), source=Path("./my-template"))

# Update an existing workspace.
update(Path("my-house"))

# The built-in template's root path (for inspection or vendoring).
print(default_template_root())
```

## License

[MIT](https://github.com/ChuMicro/ChuMicro/blob/main/LICENSE)
