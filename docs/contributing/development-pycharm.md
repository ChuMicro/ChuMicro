# Development with PyCharm

This guide covers the full development workflow in PyCharm. The project includes shared run configurations that work out of the box — open the project, set up an interpreter, and you're ready to go.

## Setup

### 1. Fork, clone, and install

Follow steps 1–4 of the [quick start](../../CONTRIBUTING.md#quick-start) in the contributing guide to fork the repository, clone it, and install dependencies. Then come back here for PyCharm-specific setup.

### 2. Open in PyCharm

**File → Open** → select the `ChuMicro` directory. PyCharm will detect it as a Python project.

### 3. Configure the Python interpreter

**File → Settings → Project → Python Interpreter**

- Click the gear icon → **Add Interpreter → Add Local Interpreter**
- Select **Virtualenv Environment → New**
- Base interpreter: Python ≥ 3.11
- Location: leave as default (`.venv` in project root)
- Click **OK**

PyCharm names the SDK `Python <major>.<minor> (chumicro)` by default. `sync-ide` seeds `.idea/misc.xml` with that same name so the committed run configurations and `chumicro.iml` resolve with no extra clicks. If you attach an interpreter that is already registered under a different name — a shared `uv` env, a system Python, or a reused SDK from another project — just pick it; PyCharm rewrites `misc.xml` with the correct name.

### 4. Run workspace setup

Open the built-in terminal (**View → Tool Windows → Terminal**, or `⌥F12` / `Alt+F12`) and run:

```bash
python scripts/run.py setup
```

This installs dependencies, runs editable installs for every library and support package, regenerates IDE configs, and creates starter `devices.yml` / `chumicro-dev-config.toml` if they are missing.  The starter `devices.yml` ships an empty registry — register a connected board with `python scripts/run.py add-device <id> --address <port>` (a thin shim around `chumicro-workspace add-device` that probes hardware identity and fills in defaults on first registration).  See [device-testing.md](device-testing.md) for the full add-device flow.

`setup` produces a lot of output — look for this at the end:

```
============================================================
  Workspace is ready
============================================================
```

## Import resolution

The mono-workspace layout means each library has its own `src/` directory. PyCharm resolves imports via source roots configured in `.idea/chumicro.iml`. This file is tracked in git so source roots stay in sync across contributors — `sync-ide` regenerates it from the live workspace layout, and the committed copy uses `<orderEntry type="inheritedJdk" />` so it does not pin anyone to a specific SDK name. You should see no red underlines on imports like `from chumicro_timing import ticks_ms`.

PyCharm may rewrite `chumicro.iml` when the interpreter or module settings change (most commonly right after you pick or swap the project SDK). When that happens, restore the managed layout before committing by running `python scripts/run.py sync-ide` — or, since re-syncing is common, click the **Sync IDE** run configuration from the toolbar. `python scripts/run.py setup` and `python scripts/prepare_workspace.py` also regenerate it as part of their normal workflow.

If imports show as unresolved:

1. Run `python scripts/run.py sync-ide` in the terminal
2. Right-click the project root → **Reload from Disk**
3. If still broken: **File → Invalidate Caches → Invalidate and Restart**

> **Note:** PyCharm uses source root configuration for import resolution — you don't need to run `pip install -e` manually. The workspace setup script handles editable installs automatically.

## Run configurations

The project includes pre-configured run configurations in `.idea/runConfigurations/`. After opening the project, the run dropdown (top-right toolbar) shows all the common tasks — no terminal required:

| Configuration | What it runs |
|--------------|-------------|
| **Preflight** | Full CI gate — lint, test, build, docs, examples, compat |
| **Lint** | Ruff across the workspace |
| **Test** | CPython tests for all libraries |
| **Test Scripts** | Infrastructure tests for `scripts/` |
| **Build** | Build all package distributions |
| **Verify Examples** | AST-based import check of all examples |
| **Docs** | Build documentation for all libraries |
| **Docs Preview** | Deploy and serve versioned docs locally |
| **Check API** | Detect API breakages against the last release tag |
| **Check Version** | Verify VERSION bumps for changed libraries |
| **Test MicroPython** | Library unit tests on the MicroPython unix port |
| **Test CircuitPython** | Library unit tests on the CircuitPython unix port |
| **Test All Runtimes** | Unit tests on CPython + MicroPython + CircuitPython (parallelized) |
| **Setup** | `python scripts/run.py setup` — installs dev deps, runs editable installs, regenerates IDE configs, generates starter device configs |
| **Prepare Workspace** | Lower-level workspace prep — invokes `scripts/prepare_workspace.py` directly (advanced users; `Setup` is usually what you want) |
| **Test Functional** | Run all hardware-gated functional suites — `test-libraries-functional` then `test-workbench-functional` against `devices.yml` defaults |
| **Test Libraries Functional** | Run defaults-backed real-board functional tests for library code |
| **Test Workbench Functional** | Run hardware-gated functional tests for every `workbench/*/functional_tests/` suite |

Click the ▶ button or press `⌃R` / `Shift+F10` to run the selected configuration.

## Running tests

### From the run configuration (with coverage)

Select **Test** from the dropdown and click ▶. This runs all libraries with the coverage threshold and leaves a `.coverage` data file at the project root. To see coverage in the editor afterward, see [Browsing coverage](#browsing-coverage) below.

To test a single library, use the terminal:

```bash
python scripts/run.py test --libraries timing
```

### From a test file (quick check, no coverage)

Right-click a test file or test function in the editor → **Run 'test_...'**. PyCharm runs it with pytest using the source roots from `.idea/chumicro.iml`. This is fast for iterating on a single test but does not produce coverage data.

For real-board `functional_tests/`, the same play buttons route to hardware once `devices.yml` is configured. Run `python scripts/run.py setup`, fill in `devices.yml` and `device-config.yml`, then right-click a `libraries/<name>/functional_tests/test_*.py` file, function, or the whole `functional_tests/` directory.

For device-backed `functional_tests/`, the test tree includes synthetic nodes such as `Setup — MicroPython`, `Run overhead — MicroPython`, `Setup — CircuitPython`, and `Run overhead — CircuitPython`. The setup node owns staging time. Individual test functions show the durations reported by the on-device harness, while the run-overhead node keeps only the remaining batch overhead that is not attributable to a single test.

Large CircuitPython RAM-mode functional tests are sent in multiple raw-REPL chunks instead of one giant inline bootstrap. Before sending those chunks, the transport asks the board for its live free heap (`gc.collect()` then `gc.mem_free()`), strips docstrings from staged library and harness source, and sizes each chunk conservatively from the measured RAM budget. If a single chunk still cannot fit, the run fails early with a flash-mode hint. In that case, set the board's `deploy_mode: flash` in `devices.yml` or use the CLI with `--deploy-mode flash`.

> **Note:** PyCharm also offers **Run with Coverage** (shield icon). This uses PyCharm's built-in coverage runner, which doesn't understand the project's multi-library layout. Use the **Test** run config or the terminal for accurate coverage.

### From the terminal

The built-in terminal (`⌥F12` / `Alt+F12`) works the same as any terminal:

```bash
python scripts/run.py test --libraries timing
```

For real-board runs:

```bash
python scripts/run.py test-libraries-functional
python scripts/run.py test-libraries-functional --library timing
python scripts/run.py test-libraries-functional --runtime both
```

Bare `test-libraries-functional` uses the `defaults:` section in `devices.yml` to choose the active board(s) and runtime(s). See [Device Testing](device-testing.md) for the schema, deploy modes, and per-runtime override flags.

## Validating your work

### Quick validation (during development)

1. Right-click your test file → **Run** (verifies tests pass)
2. Fix any red test results in the Run panel

### Full validation (before opening a PR)

Select **Preflight** from the run dropdown and click ▶.

**When it passes** — the Run panel shows:

```
Preflight passed — required CI checks should pass.

Process finished with exit code 0
```

**When it fails** — the Run panel shows the failing step. Look for lines starting with `FAIL` or `ERROR`. Common failures:

| What you see | What it means | How to fix |
|---|---|---|
| `Required test coverage of 85.0% not reached` | Tests don't cover enough code | Follow the hint below the FAIL line — it points to the `Missing` column. |
| `ruff check` errors | Code style violation — see [Style Guide](style-guide.md) | Click the file:line link in the output to jump to the issue |
| `griffe warnings detected` | Bad or missing docstrings | Add type annotations to the signature; `Args:` uses `name: description` (no type), `Returns:` uses just the description |
| `check-version` failure | Source changed without VERSION bump | Edit `libraries/<name>/VERSION` |

If the output isn't enough to pinpoint the problem, run the individual configurations (Lint, Test, Docs, etc.) from the dropdown to isolate the failing step.

### Useful shortcuts

| Action | macOS | Windows/Linux |
|--------|-------|--------------|
| Run current configuration | `⌃R` | `Shift+F10` |
| Run current test | `⌃⇧R` | `Ctrl+Shift+F10` |
| Open terminal | `⌥F12` | `Alt+F12` |
| Find in files | `⌘⇧F` | `Ctrl+Shift+F` |
| Navigate to file | `⌘⇧O` | `Ctrl+Shift+N` |
| Navigate to symbol | `⌘⌥O` | `Ctrl+Shift+Alt+N` |

## Browsing coverage

Running **Test** from the ▶ button (or `python scripts/run.py test` from the terminal) produces a `.coverage` file at the project root. You can view it two ways:

**In the editor gutter:** **Run → Show Code Coverage Data** → select the `.coverage` file. Covered lines show green; missed lines show red. This makes it easy to spot untested branches while editing.

**In a browser:** Generate an HTML report for a full clickable overview:

```bash
python -m coverage html
open htmlcov/index.html
```

> `htmlcov/` is gitignored — generate it when you need it, discard when you're done.

## Quirks and tips

- **PyCharm may suggest installing packages.** Ignore these suggestions — the project resolves imports through source roots, not pip installs.
- **If a new library is added**, run `python scripts/run.py sync-ide` (or click the **Sync IDE** run configuration). New source roots appear after reloading.
- **If choosing an interpreter rewrites `.idea/chumicro.iml`,** run **Sync IDE** (or `python scripts/run.py sync-ide`) to restore the managed source-root layout before committing. `Setup` and `Prepare Workspace` do the same regeneration if you want a fuller refresh.
- **The `.idea/` directory is partially committed** — `modules.xml`, `chumicro.iml`, run configurations, and inspection profiles are shared. Workspace-specific files (`.idea/workspace.xml`, `.idea/misc.xml`, etc.) are gitignored. `sync-ide` seeds `misc.xml` with a `Python <major>.<minor> (chumicro)` SDK hint only when it is missing — PyCharm owns it after that.
- **Run `sync-ide` from the main checkout, not a worktree.** `.idea/chumicro.iml` stores source-folder entries as `$MODULE_DIR$`-relative paths. Running `scripts/run.py sync-ide` from inside a git worktree (`.claude/worktrees/<name>/`, etc.) writes paths relative to the worktree's own root, so a commit of the regenerated `.iml` from that checkout drags wrong paths into `main`. If you have to edit IDE config while another task is open in a worktree, `cd` back to the main checkout first.
