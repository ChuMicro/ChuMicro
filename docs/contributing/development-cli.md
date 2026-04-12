# Development with the Command Line

This guide covers the full development workflow using only the terminal — no IDE required. It shows what to run, what the output looks like when things work, and what to do when they don't.

## Setup

If you haven't already, fork and clone the repository following the [quick start](../../CONTRIBUTING.md#quick-start) in the contributing guide. Then install dependencies:

```bash
cd ChuMicro
python scripts/prepare_workspace.py --create-venv
```

The `--create-venv` flag creates a `.venv` if one doesn't already exist. Omit it if you have a virtual environment already activated — the script will use whichever environment is active.

The setup script installs dependencies, then runs lint and tests to verify the workspace. It produces a lot of output — look for this at the end:

```
============================================================
  Workspace is ready
============================================================
```

If setup fails, check that Python ≥ 3.11 is installed: `python --version`.

## Running tasks

Everything goes through a single entry point: `scripts/run.py`. You don't need to remember separate tool commands — just the task name:

```bash
python scripts/run.py <task> [options]
```

Here's what each task does and how to read its output.

### Lint

Checks code style across the entire workspace using [Ruff](https://docs.astral.sh/ruff/) and the `CHU001` naming check. See the [Style Guide](style-guide.md) for what the rules are and why they exist. Fast and usually the first thing to run.

```bash
python scripts/run.py lint
```

**When it passes:**

```
+ python -m ruff check scripts support/test_harness/src ...
All checks passed!
```

**When it fails:**

```
libraries/timing/src/chumicro_timing/ticks.py:42:5: F841 Local variable `x` is assigned to but never used
Found 1 error.
```

**How to fix:** Open the file, go to the line number shown, fix the issue. Common lint errors:

| Code | Meaning | Fix |
|------|---------|-----|
| `F841` | Unused variable | Remove it or use it |
| `F401` | Unused import | Remove the import |
| `E501` | Line too long | Break the line |
| `E302` | Expected 2 blank lines | Add blank lines between top-level definitions |

### Test

Runs pytest for one or more libraries. Each library is tested in its own subprocess to avoid import collisions, and every library must meet a **94% branch coverage** threshold independently.

```bash
# Test one library
python scripts/run.py test --libraries timing

# Test all libraries
python scripts/run.py test --all

# Quick iteration — skip coverage, stop on first failure, verbose
python scripts/run.py test -k timing/test_heartbeat -x -v --no-cov
```

**When it passes:**

```
libraries/timing/tests/test_heartbeat.py .........                       [ 37%]
libraries/timing/tests/test_ticks.py .......                             [ 66%]
libraries/timing/tests/test_ticks_pytest.py ........                     [100%]

================================ tests coverage ================================

Required test coverage of 94.0% reached. Total coverage: 100.00%
============================== 24 passed in 0.04s ==============================
```

Followed by a coverage report:

```
Name                                                Stmts   Miss Branch BrPart  Cover   Missing
-----------------------------------------------------------------------------------------------
libraries/timing/src/chumicro_timing/__init__.py        3      0      0      0   100%
libraries/timing/src/chumicro_timing/heartbeat.py      23      0      6      0   100%
libraries/timing/src/chumicro_timing/testing.py        11      0      0      0   100%
libraries/timing/src/chumicro_timing/ticks.py          39      0     10      0   100%
-----------------------------------------------------------------------------------------------
TOTAL                                                  76      0     16      0   100%
```

**When a test fails:**

```
libraries/timing/tests/test_heartbeat.py::test_heartbeat_ready F

FAILED libraries/timing/tests/test_heartbeat.py::test_heartbeat_ready
  AssertionError: assert False == True
```

**How to fix:** Read the assertion error. The test name and line number point you to the failing test. Common issues:

- Wrong expected value → update the test or fix the code
- `ImportError` → missing import or wrong module name
- `AttributeError` → typo in method/attribute name

**When coverage is too low:**

```
FAIL Required test coverage of 94.0% not reached. Total coverage: 87.50%

Hint: check the Missing column above to find uncovered lines.  If the gap is
in code you didn't change, note it in your PR — a maintainer can help.
```

> **Don't panic.** The 94% threshold is about the whole library, not just your change. If the uncovered lines are in code you didn't write, that's not your fault. Note it in your PR description and move on — a maintainer can help fill the gap or mark an exception.

**How to fix:** Follow the hint — the `Missing` column in the coverage table above shows the uncovered line numbers. Write tests that exercise those lines.

**Browsing coverage in detail:**

The test command leaves a `.coverage` data file at the repository root. You can generate an HTML report for line-by-line browsing:

```bash
python -m coverage html
open htmlcov/index.html    # macOS — use xdg-open on Linux, start on Windows
```

The report shows every source file with covered lines in green and missed lines in red. Click any file to see exactly which branches are uncovered — much easier than reading line numbers from the terminal.

> **Tip:** `htmlcov/` is gitignored. Generate it whenever you need it, discard it when you're done.


### Preflight

Preflight runs everything CI will run. Always run it before opening a PR:

```bash
python scripts/run.py preflight
```

> **Lots of output?** Pipe through `tail` to see just the summary: `python scripts/run.py preflight 2>&1 | tail -5`. The `2>&1` merges error output with normal output, and `tail -5` shows just the last 5 lines.

**When it passes:**

```
Preflight passed — required CI checks should pass.
```

**When it fails** — the output will show which step failed. Scroll up to see the full output, or pipe to `less`:

```bash
python scripts/run.py preflight 2>&1 | less
```

Look for lines starting with `FAIL` or `ERROR`. Fix the issue and run preflight again.

<details>
<summary>Other tasks (expand for full list)</summary>

```bash
# Test scripts infrastructure
python scripts/run.py test-scripts

# Verify example scripts parse and import correctly
python scripts/run.py verify-examples --libraries timing

# Build docs (catches malformed docstrings)
python scripts/run.py docs --libraries timing

# Build distributable packages
python scripts/run.py build

# Regenerate IDE configuration files
python scripts/run.py sync-ide

# Scaffold a new library
python scripts/run.py new-library my-thing

# Serve a versioned docs preview locally
python scripts/run.py docs-preview --libraries timing

# Cross-runtime tasks
python scripts/run.py prepare-micropython
python scripts/run.py prepare-circuitpython
python scripts/run.py prepare-mpy-cross
python scripts/run.py test-micropython-compatibility
python scripts/run.py test-circuitpython-compatibility
python scripts/run.py test-runtime-matrix

# CI checks (run automatically in preflight)
python scripts/run.py check-version
python scripts/run.py check-api
```

Most of these run automatically as part of preflight — you only need them for targeted debugging.

</details>


