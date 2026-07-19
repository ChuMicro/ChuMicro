# Development with Other Editors

<img src="../../support/docs/chumicro_tip.png" align="left" width="64" style="margin-right: 16px; margin-bottom: 8px;">

This guide is for developers using editors other than PyCharm and VS Code: Neovim, Zed, Emacs, Sublime Text, Fleet, or anything else with a terminal.  You don't need IDE-specific configuration to work in this project.

<br clear="left">

## Setup

Follow steps 1–4 of the [setup walkthrough](../../CONTRIBUTING.md#setting-up) in the contributing guide to fork the repository, clone it, and install dependencies:

```bash
cd ChuMicro
python scripts/prepare_workspace.py
```

This auto-detects or creates `.venv`, installs dependencies, runs **editable installs** (`pip install -e`) for every library and support package, then runs lint + host tests to verify the install. Look for `Workspace is ready` at the end.

After the first run, `python scripts/run.py setup` is what refreshes the workspace day-to-day: same install + IDE sync + starter device-config generation.

Activate the venv before opening your editor so it picks up the right interpreter:

```bash
source .venv/bin/activate
```

## Why imports work without extra configuration

The workspace setup does two things that make imports resolve in any editor:

1. **Editable installs:** `prepare_workspace.py` runs `pip install -e` for every library. This registers each package with Python's import system, so `from chumicro_timing import ticks_ms` works in any tool that uses the venv's interpreter: debuggers, REPLs, linters, test runners, and language servers. (PyCharm uses source-root configuration instead of relying on editable installs; for most other editors, the editable installs are what make imports work.)

2. **`pyrightconfig.json`**: sits at the project root with `extraPaths` pointing to every library's `src/` directory. Any editor that uses [Pyright](https://github.com/microsoft/pyright) as its language server (directly or via [basedpyright](https://github.com/DetachHead/basedpyright), [pylsp](https://github.com/python-lsp/python-lsp-server), etc.) picks this up automatically.

If your editor uses a different language server (e.g., Jedi), the editable installs are sufficient.  Jedi resolves imports through the Python environment, not `pyrightconfig.json`.

## Running tasks

Tests go through plain `pytest`; other tasks go through `scripts/run.py` in the terminal.  No editor-specific task runners to set up:

```bash
pytest libraries/timing/tests/                                  # test one library (everyday)
python scripts/run.py test-libraries-functional --library timing  # real-board functional tests
python scripts/run.py lint                                       # lint the workspace
python scripts/run.py preflight                                  # full CI mirror
```

See the [Cheat Sheet](cheat-sheet.md) for the full command list.

## Real-board functional tests

When you need to run `functional_tests/` on a real board:

```bash
python scripts/run.py setup
python scripts/run.py test-libraries-functional
```

`setup` materializes three gitignored starter files at the repo root: `devices.yml`, `workspace.yml`, and `secrets.toml`.  See [Device Testing](device-testing.md) for board registration and `secrets.toml` setup, then use:

```bash
python scripts/run.py test-libraries-functional --library timing
python scripts/run.py test-libraries-functional --runtime both
python scripts/run.py test-libraries-functional --library timing --deploy-mode flash
```

If your editor has a pytest integration, explicit `functional_tests/` targets use the same pytest device plugin as PyCharm and VS Code. The CLI path above is still the fallback when an editor doesn't have pytest integration. See [Device Testing](device-testing.md) for the config schema and workflow details.

## Editor-specific tips

### Neovim / Helix (Pyright or basedpyright)

Point your LSP at the venv interpreter. `pyrightconfig.json` is detected automatically:

```lua
-- Example for nvim-lspconfig
require("lspconfig").pyright.setup({
  settings = {
    python = {
      pythonPath = ".venv/bin/python",
    },
  },
})
```

No additional `extraPaths` configuration is needed.  The root `pyrightconfig.json` handles it.

### Zed

Zed uses Pyright by default and reads `pyrightconfig.json` automatically. Select the `.venv` interpreter in the project settings and imports resolve.

### Emacs (lsp-mode / eglot)

Both `lsp-mode` and `eglot` support Pyright. Launch Emacs from a shell with the venv activated, or point Pyright at the venv directly via the `venvPath` / `venv` keys in `pyrightconfig.json`; either way Pyright reads `pyrightconfig.json` from the project root.

### Sublime Text (LSP-pyright)

Install `LSP-pyright` via Package Control. It reads `pyrightconfig.json` automatically. Set the Python interpreter to `.venv/bin/python` in project settings.

### Any other editor

If your editor has a terminal, you're ready. The CLI workflow is the primary path.  The PyCharm and VS Code guides are convenience wrappers around the same `scripts/run.py` commands.

## Browsing coverage reports

After running tests, a `.coverage` data file is left at the repository root. For the HTML report and the rest of the coverage workflow, see [Browsing coverage](style-guide.md#browsing-coverage) in the Style Guide.

Many editors also have coverage-gutter plugins that read the data directly; check your editor's plugin ecosystem for a "coverage" integration. Most read either `.coverage` (SQLite) or `coverage.xml` (generate with `python -m coverage xml`).

## When a new library is added

Run setup again to register the new package:

```bash
python scripts/run.py setup
```

This re-runs editable installs and regenerates `pyrightconfig.json`. Your editor's language server will pick up the new library after a restart or workspace reload.

## Validation checklist

Run preflight before opening a PR:

```bash
python scripts/run.py preflight
# Expected: "Preflight passed.  Required CI checks should pass."
```
