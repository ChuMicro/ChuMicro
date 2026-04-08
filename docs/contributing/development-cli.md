# Development with the Command Line

This guide covers the full development workflow using only the terminal — no IDE required. It shows what to run, what the output looks like when things work, and what to do when they don't.

## Setup

```bash
# Clone (or fork first, then clone your fork)
git clone https://github.com/ChuMicro/ChuMicro.git
cd ChuMicro

# Install dependencies, run lint + tests to verify
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

Checks code style across the entire workspace using [Ruff](https://docs.astral.sh/ruff/). Fast and usually the first thing to run.

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

Runs pytest for one or more libraries. Each library is tested in its own subprocess to avoid import collisions, and every library must hit **94% branch coverage** independently.

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
```

**How to fix:** Look at the `Missing` column in the coverage report. It shows the line numbers not covered by tests. Write tests that exercise those lines.

### Verify examples

Checks that every example script in a library has valid syntax and resolvable imports. Quick to run — catches copy-paste mistakes before they reach users.

```bash
python scripts/run.py verify-examples --libraries timing
```

**When it passes:**

```
  checking libraries/timing/examples/heartbeat_blink.py
  OK:   libraries/timing/examples/heartbeat_blink.py
  ...
All 9 example(s) verified.
```

**When it fails:**

```
  checking libraries/timing/examples/broken_example.py
  FAIL: libraries/timing/examples/broken_example.py
    SyntaxError: invalid syntax (line 12)
```

**How to fix:** Open the example file and fix the syntax error at the reported line.

### Build docs

Builds the MkDocs documentation site for a library. Docstrings are rendered into API reference pages by mkdocstrings, so this also catches malformed docstrings.

```bash
python scripts/run.py docs --libraries timing
```

**When it passes:**

```
== docs libraries/timing ==
Build started
+ /
+ /testing/
+ /guide/
+ /api/
Build finished in 0.00s
  Built: libraries/timing/site/
```

**When it fails** (common: griffe warning from bad docstrings):

```
WARNING  -  griffe: chumicro_timing/core.py:42: No type in parameter 'interval_ms'
FAIL: griffe warnings detected — fix docstrings before merging.
```

**How to fix:** Add the type to the docstring parameter. Use Google-style format:

```python
def my_func(interval_ms):
    """Do something.

    Args:
        interval_ms (int): Interval in milliseconds.  ← add the (int) part
    """
```

### Preflight

Preflight runs everything CI will run. Always run it before opening a PR:

```bash
python scripts/run.py preflight 2>&1 | tail -5
```

**When it passes:**

```
Preflight passed — required CI checks should pass.
```

**When it fails:**

The output will show which step failed. Scroll up or omit the `tail` to see the full output:

```bash
python scripts/run.py preflight 2>&1 | less
```

Look for lines starting with `FAIL` or `ERROR`. Fix the issue and run preflight again.

### Build

Builds distributable packages (`.tar.gz` and `.whl`) for all libraries. You rarely need this during development — preflight runs it for you — but it's useful to verify packaging independently.

```bash
python scripts/run.py build
```

**When it passes:**

```
== build libraries/timing ==
...
Successfully built chumicro_timing-0.1.15.tar.gz and chumicro_timing-0.1.15-py3-none-any.whl
Built 4 package(s): libraries/compat, libraries/msgpack, libraries/runner, libraries/timing
```

## Commit workflow

Stage your changes and commit. Git opens your default editor for the message:

```bash
git add -A
git commit
```

The commit message format:

```
Imperative subject line (what this commit does)

Body explaining *why*, not *what*. The diff shows what changed.
Name affected libraries.

Affects: timing, runner
```

Use imperative mood in the subject — "Fix wraparound bug", not "Fixed" or "Fixes".

## Validation checklist

Before opening a PR, verify your changes pass all checks. Run them in order — each is progressively broader:

```bash
# 1. Lint (fastest — catches formatting issues)
python scripts/run.py lint

# 2. Test the libraries you changed
python scripts/run.py test --libraries <name>

# 3. Verify examples parse
python scripts/run.py verify-examples --libraries <name>

# 4. Build docs
python scripts/run.py docs --libraries <name>

# 5. Full preflight (runs everything — do this last)
python scripts/run.py preflight 2>&1 | tail -5
```

What "valid" means:

| Check | What it verifies | Pass condition |
|-------|-----------------|----------------|
| `lint` | Code style (Ruff) | Zero errors |
| `test` | Correctness + coverage | All tests pass, ≥ 94% branch coverage per library |
| `verify-examples` | Example files parse | All examples have valid syntax and resolvable imports |
| `docs` | Documentation builds | Zero griffe warnings, clean build |
| `build` | Package creates correctly | `.tar.gz` and `.whl` produced |
| `check-version` | VERSION bump if source changed | VERSION file bumped when `src/` files changed |
| `check-api` | No unintentional API breakage | No removed/renamed public symbols without VERSION bump |
| `MicroPython compat` | Code runs on MicroPython | Cross-runtime unit tests pass |
| `CircuitPython compat` | Code runs on CircuitPython | Cross-runtime unit tests pass |

Steps 1–4 catch most issues. Preflight (step 5) catches the rest.

