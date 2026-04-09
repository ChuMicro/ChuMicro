# Development with Other Editors

This guide is for developers using editors other than PyCharm and VS Code — Neovim, Zed, Emacs, Sublime Text, Fleet, or anything else with a terminal. You don't need IDE-specific configuration to work in this project.

## Setup

Follow the same steps as the [Command Line guide](development-cli.md#setup):

```bash
git clone https://github.com/ChuMicro/ChuMicro.git
cd ChuMicro
python scripts/prepare_workspace.py --create-venv
```

This creates a `.venv`, installs dependencies, runs **editable installs** (`pip install -e`) for every library, and verifies the workspace. Look for `Workspace is ready` at the end.

Activate the venv before opening your editor so it picks up the right interpreter:

```bash
source .venv/bin/activate
```

## Why imports work without extra configuration

The workspace setup does two things that make imports resolve in any editor:

1. **Editable installs** — `prepare_workspace.py` runs `pip install -e` for every library. This registers each package with Python's import system, so `from chumicro_timing import ticks_ms` works in any tool that uses the venv's interpreter — debuggers, REPLs, linters, test runners, and language servers.

2. **`pyrightconfig.json`** — sits at the project root with `extraPaths` pointing to every library's `src/` directory. Any editor that uses [Pyright](https://github.com/microsoft/pyright) as its language server (directly or via [basedpyright](https://github.com/DetachHead/basedpyright), [pylsp](https://github.com/python-lsp/python-lsp-server), etc.) picks this up automatically.

If your editor uses a different language server (e.g., Jedi), the editable installs are sufficient — Jedi resolves imports through the Python environment, not `pyrightconfig.json`.

## Running tasks

All tasks go through `scripts/run.py` in the terminal. There are no editor-specific task runners to set up:

```bash
python scripts/run.py test --libraries timing   # test one library
python scripts/run.py lint                       # lint the workspace
python scripts/run.py preflight 2>&1 | tail -5   # full CI gate
```

See the [Command Line guide](development-cli.md#running-tasks) for the full list with expected output.

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

No additional `extraPaths` configuration is needed — the root `pyrightconfig.json` handles it.

### Zed

Zed uses Pyright by default and reads `pyrightconfig.json` automatically. Select the `.venv` interpreter in the project settings and imports resolve.

### Emacs (lsp-mode / eglot)

Both `lsp-mode` and `eglot` support Pyright. Activate the venv before starting Emacs (or configure `python-shell-virtualenv-root`), and Pyright will read `pyrightconfig.json` from the project root.

### Sublime Text (LSP-pyright)

Install `LSP-pyright` via Package Control. It reads `pyrightconfig.json` automatically. Set the Python interpreter to `.venv/bin/python` in project settings.

### Any other editor

If your editor has a terminal, you're ready. The CLI workflow is the canonical one — the PyCharm and VS Code guides are convenience wrappers around the same `scripts/run.py` commands.

## Browsing coverage reports

After running tests, a `.coverage` data file is left at the repository root. Generate an HTML report for line-by-line browsing:

```bash
python scripts/run.py test --libraries timing
python -m coverage html
open htmlcov/index.html    # macOS — use xdg-open on Linux
```

The report highlights covered lines in green and missed lines in red. Click any file to see exactly which branches need tests. `htmlcov/` is gitignored.

Some editors also have coverage gutter plugins that read coverage data directly — check your editor's plugin ecosystem for "coverage" integrations. Most read either `.coverage` (SQLite) or `coverage.xml` (generate with `python -m coverage xml`).

## When a new library is added

Run setup again to register the new package:

```bash
python scripts/run.py setup
```

This re-runs editable installs and regenerates `pyrightconfig.json`. Your editor's language server will pick up the new library after a restart or workspace reload.

## Validation checklist

Same as the [CLI guide](development-cli.md#validation-checklist) — run preflight before opening a PR:

```bash
python scripts/run.py preflight 2>&1 | tail -5
# Expected: "Preflight passed — required CI checks should pass."
```

