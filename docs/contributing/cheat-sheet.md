# Contributor Cheat Sheet

Everything you need to know on one page. The full docs are linked if you want details.

## Setup (once)

```bash
git clone https://github.com/<your-username>/ChuMicro.git
cd ChuMicro
git remote add upstream https://github.com/ChuMicro/ChuMicro.git
python scripts/prepare_workspace.py                 # first-time bootstrap
source .venv/bin/activate                           # then activate the venv
```

**Why `prepare_workspace.py`?** It's the only command that runs on a fresh clone with zero third-party packages installed — it auto-detects or creates `.venv`, installs every library and support package, and runs lint + host tests to confirm the install. After that, your environment is live.

**For everyday refreshes** — after a `git pull` that touches dependencies or adds a library — run `python scripts/run.py setup`. It's idempotent and does the same install/refresh work, but it assumes the venv already exists.

## Workflow (every change)

```bash
git checkout main && git pull upstream main && git push origin main
git checkout -b fix/my-change
# ... make changes ...
python scripts/run.py preflight       # must print "Preflight passed"
git add -A && git commit              # imperative subject, explain why
git push -u origin fix/my-change      # then open PR on GitHub
```

## The 10 things

1. **One command to rule them all:** `python scripts/run.py preflight`. If it passes, CI will pass.
2. **Use descriptive names.** The linter catches abbreviations and suggests replacements. Single-letter for-loop targets (`for i in range(10)`) are fine.
3. **No `async`/`await`.** Use the tick-based runner. It's easier to test and debug on microcontrollers.
4. **Accept dependencies as constructor parameters.** Don't import `board` or `busio` at the top level. This makes code testable without hardware.
5. **Tests live next to the code.** `libraries/<name>/tests/`. Run them with `python scripts/run.py test --libraries <name>`.
6. **Bump VERSION when you change source code.** Edit `libraries/<name>/VERSION`. CI catches it if you forget.
7. **Docstrings are required** on public functions. Types go on the signature, descriptions in the docstring.
8. **f-strings everywhere.** No `%` formatting, no `.format()`.
9. **`const()` and `memoryview` are optional on day one.** Focus on correctness first, optimize later.
10. **Update docs that your change affects.** Not 10 files — just the ones directly impacted. Reviewers catch the rest.

## Common commands

Grouped by what you're trying to do. Preflight is the one command you actually have to remember — everything else is reference.

### Every PR

| What | Command |
|---|---|
| Run everything CI will run | `python scripts/run.py preflight` |
| Lint only | `python scripts/run.py lint` |
| Scaffold a new library | `python scripts/run.py new-library my-thing` |

### Testing

| What | Command |
|---|---|
| Run all CPython package tests | `python scripts/run.py test --all` |
| Test one library | `python scripts/run.py test --libraries timing` |
| Filter by test name (vanilla pytest style) | `python scripts/run.py test -k heartbeat` |
| Filter scoped to one library | `python scripts/run.py test -k timing/test_heartbeat` |
| Quick test (no coverage, stop on first failure) | `python scripts/run.py test -k heartbeat -x -v --no-cov` |
| Test scripts infrastructure | `python scripts/run.py test-scripts` |
| Verify examples | `python scripts/run.py verify-examples --libraries timing` |

### Cross-runtime testing

| What | Command |
|---|---|
| MicroPython unix-port compatibility | `python scripts/run.py test-micropython-compatibility` |
| CircuitPython unix-port compatibility | `python scripts/run.py test-circuitpython-compatibility` |
| All runtimes (host + both unix ports) | `python scripts/run.py test-runtime-matrix` |
| Deep local sweep (host + scripts + unix ports; `--with-device` for real boards) | `python scripts/run.py test-everything` |
| Prepare MicroPython unix-port (one-time, slow) | `python scripts/run.py prepare-micropython` |
| Prepare CircuitPython unix-port (one-time, slow) | `python scripts/run.py prepare-circuitpython` |
| Build mpy-cross only (faster than full unix-port) | `python scripts/run.py prepare-mpy-cross` |

### Device testing

| What | Command |
|---|---|
| Refresh workspace + generate starter device configs | `python scripts/run.py setup` |
| Run real-board functional tests | `python scripts/run.py test-device --library timing` |
| Run real-board tests on both runtimes | `python scripts/run.py test-device --runtime both` |
| Run workbench hardware-gated functional tests | `python scripts/run.py test-workbench --workbench deploy` |

### Docs and publishing

| What | Command |
|---|---|
| Build docs for one library | `python scripts/run.py docs --libraries timing` |
| Validate mip install against a bundle repo | `python scripts/run.py validate-mip --bundle-repo ChuMicro-Bundle-Experimental --libraries timing` |

## When something fails

Every failure message tells you exactly what to do.

| What failed | What to do |
|---|---|
| Lint error | Run `python scripts/run.py lint`, fix the flagged lines — the error message tells you what's wrong |
| Test failure | Read the assertion error — the test name and line number point you right to it |
| Coverage too low | The gate is 85 % (configured in `pyproject.toml`). Check the `Missing` column for uncovered line numbers. If it's code you didn't write, note it in the PR. For hardware-only code that can't be tested on CPython, see [coverage exclusions](style-guide.md#coverage-exclusions) |
| `check-version` | Edit `libraries/<name>/VERSION` (patch bump is usually right) |
| `griffe warnings` | Add type annotations to function signatures |
| `functional_tests/` say no device is configured | Run `python scripts/run.py setup`, then fill in `devices.yml`. See [device testing](device-testing.md) |
| Stuck or confused | Ask in the PR — someone will help |

**Browsing coverage in detail:** After running tests, generate an HTML report with `python -m coverage html` and open `htmlcov/index.html`. Covered lines show in green, missed lines in red — much easier than reading line numbers from the terminal. (`htmlcov/` is gitignored.)

## Links

- [Full contributing guide](../../CONTRIBUTING.md)
- [Style guide](style-guide.md)
- [PR guide](pull-requests.md)
- [Device testing](device-testing.md)
- [Design decisions](../../plans/decisions/README.md)
