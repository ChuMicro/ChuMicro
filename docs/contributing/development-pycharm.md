# Development with PyCharm

<img src="https://chumicro.com/assets/chumicro-head.png" alt="" align="left" width="64" style="margin-right: 16px; margin-bottom: 8px;">

The project ships run configurations under `.idea/runConfigurations/`.  Once PyCharm has the project's interpreter, its run dropdown lists every common task.

<br clear="left">

## Setup

### 1. Fork, clone, and install

Follow steps 1 to 4 of [CONTRIBUTING § Setting up](https://github.com/ChuMicro/ChuMicro/blob/main/CONTRIBUTING.md#setting-up).

### 2. Open in PyCharm

**File → Open**, then select the `ChuMicro` directory.  PyCharm detects it as a Python project.

### 3. Configure the Python interpreter

The bootstrap in step 1 created `.venv` in the project root.  Point PyCharm at it rather than creating a new one:

**File → Settings → Project → Python Interpreter** (**PyCharm → Settings** on macOS)

- Click **Add Interpreter → Add Local Interpreter**
- Choose the existing virtualenv and select `.venv/bin/python` in the project root (`.venv\Scripts\python.exe` on Windows)
- Click **OK**

PyCharm names the SDK `Python <major>.<minor> (chumicro)` by default.  `sync-ide` seeds `.idea/misc.xml` with that same name, so the committed run configurations and `chumicro.iml` resolve with no extra clicks.  An interpreter already registered under another name, such as a shared `uv` environment, a system Python, or an SDK from another project, works too: pick it, and PyCharm rewrites `misc.xml` with its name.

### 4. Re-sync the IDE config

Picking an interpreter can make PyCharm rewrite `.idea/chumicro.iml`.  Open the built-in terminal with **View → Tool Windows → Terminal**, or `⌥F12` / `Alt+F12`, and restore the managed layout:

```bash
python scripts/run.py sync-ide
```

For functional tests on a real board, [Device Testing](device-testing.md) covers board registration and `secrets.toml`.

## Import resolution

Each library has its own `src/` folder, and PyCharm resolves imports through the source roots in `.idea/chumicro.iml`.  Git tracks that file, so every contributor gets the same source roots.  `sync-ide` regenerates it from the workspace layout, and its `<orderEntry type="inheritedJdk" />` leaves each contributor's SDK name free.  Imports like `from chumicro_timing import ticks_ms` then show no red underlines.

PyCharm may rewrite `chumicro.iml` when the interpreter or module settings change, most often right after you pick or swap the project SDK.  Restore the managed layout before committing, with `python scripts/run.py sync-ide` or the **Sync IDE** run configuration.

When imports show as unresolved:

1. Run `python scripts/run.py sync-ide` in the terminal
2. Right-click the project root, then **Reload from Disk**
3. If they are still unresolved: **File → Invalidate Caches → Invalidate and Restart**

## Run configurations

The run dropdown in the top-right toolbar lists these configurations:

| Configuration | What it runs |
|--------------|-------------|
| **Preflight** | Every check CI runs on a PR: lint, tests on all three runtimes, build, docs, examples, size and version checks |
| **Lint** | Ruff plus the project's own `chumicro-checks` rules |
| **Test** | CPython tests for every package, with the coverage gate (`run.py test --all`) |
| **Test Scripts** | Infrastructure tests for `scripts/` |
| **Build** | Build all package distributions |
| **Verify Examples** | AST-based import check of all examples |
| **Docs** | Build documentation for all libraries |
| **Docs Preview** | Deploy and serve versioned docs locally |
| **Check API** | Detect API breakages against the last release tag |
| **Check Version** | Verify VERSION bumps for changed libraries |
| **Test MicroPython** | Library unit tests on the MicroPython unix port |
| **Test CircuitPython** | Library unit tests on the CircuitPython unix port |
| **Test All Runtimes** | Unit tests on CPython, MicroPython, and CircuitPython, in parallel |
| **Setup** | `python scripts/run.py setup`: installs dev dependencies and every package in editable mode, regenerates IDE configs, and writes the starter config files |
| **Prepare Workspace** | `scripts/prepare_workspace.py`, the first-time bootstrap.  **Setup** covers later refreshes |
| **Sync IDE** | Regenerates `.idea/chumicro.iml`, the run configurations, `pyrightconfig.json`, and the `.vscode/` config |
| **Test Functional** | Every hardware-gated functional suite: `test-libraries-functional`, then `test-workbench-functional`, against the `devices.yml` defaults |
| **Test Libraries Functional** | Real-board functional tests for library code, against the `devices.yml` defaults |
| **Test Workbench Functional** | Hardware-gated functional tests for every `workbench/*/functional_tests/` suite |

Click the ▶ button or press `⌃R` / `Shift+F10` to run the selected configuration.

## Running tests

### From the run configuration (with coverage)

**Test** runs every package with the coverage gate, and leaves a `.coverage` data file at the project root for [Browsing coverage](#browsing-coverage).

To test a single library, use the terminal:

```bash
pytest libraries/timing/tests/
```

### From a test file (quick check, no coverage)

Right-click a test file or test function in the editor, then **Run 'test_...'**.  PyCharm runs it with pytest, using the source roots from `.idea/chumicro.iml`.  This run suits iterating on a single test, and collects no coverage data.

The same right-click works on a `libraries/<name>/functional_tests/` file, function, or folder, and runs it on a board once `devices.yml` names one.

PyCharm's **Run with Coverage**, the shield icon, uses its built-in coverage runner, which misreads the project's multi-library layout.  Use the **Test** run configuration or the terminal for coverage.

## Before a pull request

Run **Preflight** from the dropdown.  [CONTRIBUTING § Reading a failure](https://github.com/ChuMicro/ChuMicro/blob/main/CONTRIBUTING.md#reading-a-failure) explains a red result.  Running **Lint**, **Test**, or **Docs** alone narrows a failing phase down.

## Useful shortcuts

| Action | macOS | Windows/Linux |
|--------|-------|--------------|
| Run current configuration | `⌃R` | `Shift+F10` |
| Run current test | `⌃⇧R` | `Ctrl+Shift+F10` |
| Open terminal | `⌥F12` | `Alt+F12` |
| Find in files | `⌘⇧F` | `Ctrl+Shift+F` |
| Navigate to file | `⌘⇧O` | `Ctrl+Shift+N` |
| Navigate to symbol | `⌘⌥O` | `Ctrl+Shift+Alt+N` |

## Browsing coverage

The **Test** configuration, or `python scripts/run.py test` in the terminal, leaves a `.coverage` file at the project root.  PyCharm shows it in the editor gutter: **Run → Show Code Coverage Data**, then select the `.coverage` file.  Covered lines show green and missed lines red, so untested branches stand out while editing.

[Style Guide § Browsing coverage](style-guide.md#browsing-coverage) covers the HTML report.

## Quirks and tips

- **Ignore PyCharm's offers to install packages.**  The project resolves imports through source roots, and the setup script already installs every package in editable mode.
- **After a new library lands**, run `python scripts/run.py sync-ide`, or the **Sync IDE** run configuration.  The new source roots appear after a reload.
- **Git tracks part of `.idea/`**: `modules.xml`, `chumicro.iml`, the run configurations, and the inspection profiles.  The other files in `.idea/`, `workspace.xml` and `misc.xml` among them, stay gitignored.  `sync-ide` writes `misc.xml` only when it is missing, and PyCharm owns it after that.
