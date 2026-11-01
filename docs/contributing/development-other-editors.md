# Development with Other Editors

<img src="https://chumicro.com/assets/chumicro-head.png" alt="" align="left" width="64" style="margin-right: 16px; margin-bottom: 8px;">

Neovim, Zed, Emacs, Sublime Text, Fleet, and any other editor with a terminal work on this project without editor-specific configuration.

<br clear="left">

## Setup

Follow steps 1 to 4 of [CONTRIBUTING § Setting up](https://github.com/ChuMicro/ChuMicro/blob/main/CONTRIBUTING.md#setting-up).  Then activate the venv before opening your editor, so the editor picks up the right interpreter:

```bash
source .venv/bin/activate
```

## Why imports work without extra configuration

1. **Editable installs.**  `prepare_workspace.py` installs every library in editable mode, which registers each package with Python's import system.  `from chumicro_timing import ticks_ms` then works in any tool that uses the venv's interpreter: debuggers, REPLs, linters, test runners, and language servers.
2. **`pyrightconfig.json`** at the project root points `extraPaths` at every library's `src/` folder.  An editor whose language server is [Pyright](https://github.com/microsoft/pyright), directly or through [basedpyright](https://github.com/DetachHead/basedpyright), reads it automatically.

A language server built on Jedi, such as [pylsp](https://github.com/python-lsp/python-lsp-server), resolves imports through the Python environment, so the editable installs cover it.

## Running tasks

Tests run through plain `pytest`, and every other task through `scripts/run.py` in the terminal:

```bash
pytest libraries/timing/tests/                                  # test one library (everyday)
python scripts/run.py test-libraries-functional --library timing  # real-board functional tests
python scripts/run.py lint                                       # lint the workspace
python scripts/run.py preflight                                  # full CI mirror
```

The [cheat sheet](cheat-sheet.md) lists every command.

## Real-board functional tests

[Device Testing](device-testing.md) covers registering a board and running `functional_tests/` from the terminal.  An editor with pytest integration runs explicit `functional_tests/` targets through the same device plugin PyCharm and VS Code use.

## Editor-specific tips

### Neovim / Helix (Pyright or basedpyright)

Point your language server at the venv interpreter.  It detects `pyrightconfig.json`, which supplies `extraPaths`:

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

### Zed

Zed uses Pyright by default and reads `pyrightconfig.json` automatically.  Select the `.venv` interpreter in the project settings, and imports resolve.

### Emacs (lsp-mode / eglot)

`lsp-mode` and `eglot` both support Pyright, which reads `pyrightconfig.json` from the project root.  Launch Emacs from a shell with the venv activated, so Pyright finds the venv's packages.

### Sublime Text (LSP-pyright)

Install `LSP-pyright` through Package Control.  It reads `pyrightconfig.json` automatically.  Set the Python interpreter to `.venv/bin/python` in the project settings.

### Any other editor

An editor with a terminal runs every task from the command line.  The PyCharm and VS Code run buttons call the same `scripts/run.py` commands.

## Browsing coverage

A test run leaves a `.coverage` data file at the repository root.  [Style Guide § Browsing coverage](style-guide.md#browsing-coverage) covers the HTML report.

Many editors have coverage-gutter plugins that read the data directly.  Most read either `.coverage`, a SQLite file, or `coverage.xml`, which `python -m coverage xml` generates.

## When a new library lands

Run setup again to register the new package:

```bash
python scripts/run.py setup
```

Setup re-runs the editable installs and regenerates `pyrightconfig.json`.  The editor's language server picks up the new library after a restart or workspace reload.

## Before a pull request

Run preflight, and read the result as [CONTRIBUTING § Reading a failure](https://github.com/ChuMicro/ChuMicro/blob/main/CONTRIBUTING.md#reading-a-failure) describes:

```bash
python scripts/run.py preflight
```
