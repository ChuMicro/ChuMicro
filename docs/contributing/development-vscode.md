# Development with VS Code

<img src="https://chumicro.com/assets/chumicro-head.png" alt="" align="left" width="64" style="margin-right: 16px; margin-bottom: 8px;">

The project ships task definitions and settings under `.vscode/`.  Once VS Code has the project's interpreter, every common task runs from the Command Palette.

<br clear="left">

## Setup

### 1. Fork, clone, and install

Follow steps 1 to 4 of [CONTRIBUTING § Setting up](https://github.com/ChuMicro/ChuMicro/blob/main/CONTRIBUTING.md#setting-up).

### 2. Open in VS Code

```bash
code ChuMicro
```

Or **File → Open Folder**, then select the `ChuMicro` directory.

### 3. Install recommended extensions

VS Code offers the extensions `.vscode/extensions.json` recommends.  Accept, or install them by hand:

- **Python** (`ms-python.python`): required
- **Pylance** (`ms-python.vscode-pylance`): type checking
- **Coverage Gutters** (`ryanluker.vscode-coverage-gutters`): coverage in the editor gutter

### 4. Select the Python interpreter

Open the Command Palette (`⌘⇧P` / `Ctrl+Shift+P`), run **Python: Select Interpreter**, and pick the `.venv` interpreter the bootstrap created.

For functional tests on a real board, [Device Testing](device-testing.md) covers board registration and `secrets.toml`.

## Import resolution

Each library has its own `src/` folder.  VS Code resolves imports through two files that `sync-ide` generates during setup:

- **`pyrightconfig.json`**: sets `extraPaths` for each library's `src/` directory
- **`.vscode/settings.json`**: sets `python.analysis.extraPaths` for Pylance

Imports like `from chumicro_timing import ticks_ms` then resolve.

When imports show as unresolved:

1. Run `python scripts/run.py sync-ide` in the terminal
2. Reload the window: Command Palette, then **Developer: Reload Window**

## Running tasks

Open the Command Palette and run **Tasks: Run Task**.  The tasks carry the same names, and run the same commands, as the PyCharm run configurations listed in [Development with PyCharm § Run configurations](development-pycharm.md#run-configurations).  Output appears in the Terminal panel at the bottom of the window.

## Running tests

### From the task runner (with coverage)

The **Test** task runs every package with the coverage gate, and leaves a `.coverage` data file at the project root for [Browsing coverage](#browsing-coverage).

### From the test explorer (quick check, no coverage)

VS Code's Testing panel, the beaker icon in the sidebar, discovers tests through the `python.testing.pytestArgs` setting in `.vscode/settings.json`.

Click the ▶ button next to any test file or function to run it.  This run suits iterating, and skips coverage collection and the coverage gate.

The same panel runs a `functional_tests/` file, folder, or function on a board once `devices.yml` names one.

## Before a pull request

Command Palette, then **Tasks: Run Task**, then **Preflight**.  [CONTRIBUTING § Reading a failure](https://github.com/ChuMicro/ChuMicro/blob/main/CONTRIBUTING.md#reading-a-failure) explains a red result.  Running **Lint**, **Test**, **Verify Examples**, or **Docs** alone narrows a failing phase down.

## Useful shortcuts

| Action | macOS | Windows/Linux |
|--------|-------|--------------|
| Open Command Palette | `⌘⇧P` | `Ctrl+Shift+P` |
| Open terminal | `` ⌃` `` | `` Ctrl+` `` |
| Run task | `⌘⇧P` → "Tasks: Run Task" | `Ctrl+Shift+P` → "Tasks: Run Task" |
| Go to file | `⌘P` | `Ctrl+P` |
| Go to symbol | `⌘⇧O` | `Ctrl+Shift+O` |
| Find in files | `⌘⇧F` | `Ctrl+Shift+F` |

## Browsing coverage

The **Test** task, or `python scripts/run.py test` in the terminal, leaves a `.coverage` data file at the project root.  To see it in the editor gutter, generate an XML report with `python -m coverage xml`, then run the **Coverage Gutters: Display Coverage** command.  [Coverage Gutters](https://marketplace.visualstudio.com/items?itemName=ryanluker.vscode-coverage-gutters) reads `coverage.xml` and highlights covered and uncovered lines in the editor.  `coverage.xml` is gitignored.

[Style Guide § Browsing coverage](style-guide.md#browsing-coverage) covers the HTML report.

## Quirks and tips

- **Pylance may flag `micropython` imports**, such as `from micropython import const`.  Those modules exist only on a board, and library code wraps them in `try` / `except ImportError`.
- **Test discovery in the sidebar may be slow** on first open.  Wait for Pylance to finish indexing, shown in the status bar.
- **After a new library lands**, run `python scripts/run.py sync-ide` to regenerate `pyrightconfig.json` and `.vscode/settings.json`, then reload the window.
- **`sync-ide` owns `.vscode/tasks.json`**, and regenerates it on every `setup` and `new-library` run, so hand edits to it disappear.  Add personal tasks through VS Code's user tasks instead.
- **Terminal links are clickable.**  When a lint error or test failure shows `file.py:42`, `Ctrl+click` / `⌘+click` jumps to that line.
- **PyCharm gets more day-to-day use**, so file any problem that shows up only in VS Code.
