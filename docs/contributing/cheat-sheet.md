# Contributor Cheat Sheet

<img src="https://chumicro.com/assets/chumicro-head.png" align="left" width="64" style="margin-right: 16px; margin-bottom: 8px;">

Everything you need to know on one page.  The full docs are linked if you want details.

<br clear="left">

## Setup (once)

Fork the repo on GitHub first, then:

```bash
git clone https://github.com/<your-username>/ChuMicro.git
cd ChuMicro
git remote add upstream https://github.com/ChuMicro/ChuMicro.git
python scripts/prepare_workspace.py                 # first-time bootstrap
source .venv/bin/activate                           # then activate the venv
```

**Why `prepare_workspace.py`?** It's the only command that runs on a fresh clone with zero third-party packages installed.  It auto-detects or creates `.venv`, installs every library and support package, and runs lint + host tests to confirm the install.  After that, your environment is live.

**For everyday refreshes** (after a `git pull` that touches dependencies or adds a library) run `python scripts/run.py setup`.  Safe to re-run any time; does the same install/refresh work as the first-time bootstrap, but assumes the venv already exists.

## Workflow (every change)

```bash
git checkout main && git pull upstream main && git push origin main
git checkout -b fix/my-change
# ... make changes ...
python scripts/run.py preflight       # must print "Preflight passed"
git add <changed files> && git commit # imperative subject, explain why
git push -u origin fix/my-change      # then open PR on GitHub
```

## The 10 rules

1. **Preflight is the one required gate.** `python scripts/run.py preflight`. If it passes, CI will pass.
2. **Use descriptive names.** The linter names the exact replacement, so each hit is mechanical; expect a few in your first PR. Single-letter for-loop targets (`for i in range(10)`) are fine. ([Decision 0022](https://github.com/ChuMicro/ChuMicro/blob/main/plans/decisions/0022-naming-conventions.md))
3. **No `async`/`await`.** CircuitPython's asyncio has a broken stream layer and every `await` allocates there; `yield from` is one bytecode on both device runtimes. Services are tick-driven (`check`/`handle`); sequential flows are generators via `runner.add_generator`. Lint-enforced. ([Decision 0087](https://github.com/ChuMicro/ChuMicro/blob/main/plans/decisions/0087-generators-for-sequential-io.md))
4. **Accept dependencies as constructor parameters.** Don't import `board` or `busio` at the top level. This makes code testable without hardware.
5. **Tests live next to the code.** `libraries/<name>/tests/`. Run them with `pytest libraries/<name>/tests/`.
6. **Bump VERSION when you change source code.** Edit `libraries/<name>/VERSION`. CI catches it if you forget.
7. **Docstrings are required** on public functions. Types go on the signature, descriptions in the docstring.
8. **f-strings everywhere.** No `%` formatting, no `.format()`.
9. **`const()` and `memoryview` are optional on day one.** Focus on correctness first, optimize later.
10. **Update docs that your change affects.** Not 10 files, just the ones directly impacted. Reviewers catch the rest.

## Common commands

Grouped by what you're trying to do. Preflight is the one command you actually have to remember; everything else is reference.

### Every PR

| What | Command |
|---|---|
| Run everything CI will run | `python scripts/run.py preflight` |
| Lint only | `python scripts/run.py lint` |
| Scaffold a new library | `python scripts/run.py new-library my-project` |
| Scaffold a host-only workbench tool | `python scripts/run.py new-library --workbench my-tool` |

### Testing

| What | Command |
|---|---|
| Test one library | `pytest libraries/timing/tests/` |
| Filter by test name | `pytest libraries/timing/tests/ -k deadline` |
| Quick test (stop on first failure, verbose) | `pytest libraries/timing/tests/ -k deadline -x -v` |
| Test a single file | `pytest libraries/timing/tests/test_deadline.py` |
| Test all CPython package tests with the coverage gate | `python scripts/run.py test --all` |
| Test one library with the coverage gate | `python scripts/run.py test --libraries timing` |
| Test scripts infrastructure | `python scripts/run.py test-scripts` |
| Verify examples | `python scripts/run.py verify-examples --libraries timing` |

Bare `pytest` from the repo root is the everyday command for iteration: fast, IDE-play-button-friendly.  `python scripts/run.py test` wraps pytest in per-library subprocesses that enforce the coverage gates ([Decision 0009](https://github.com/ChuMicro/ChuMicro/blob/main/plans/decisions/0009-per-library-test-runs.md)); preflight uses that wrapper, so you usually don't need to invoke it directly.

### Cross-runtime testing

| What | Command |
|---|---|
| Library unit tests on MicroPython unix-port | `pytest libraries/ --target unix-port --runtime micropython` |
| Library unit tests on CircuitPython unix-port | `pytest libraries/ --target unix-port --runtime circuitpython` |
| Unit tests on both unix ports | `pytest libraries/ --target unix-port --runtime both` |
| Per-file unix-port run (IDE play / single-file targeting) | `pytest libraries/timing/tests/test_deadline.py --target unix-port --runtime micropython` |
| Full CI mirror including hardware-gated functional tests | `python scripts/run.py preflight --with-functional` |
| Prepare MicroPython unix-port (one-time, slow) | `python scripts/run.py prepare-micropython` |
| Prepare CircuitPython unix-port (one-time, slow) | `python scripts/run.py prepare-circuitpython` |
| Build mpy-cross only (faster than full unix-port) | `python scripts/run.py prepare-mpy-cross` |

### Device testing

| What | Command |
|---|---|
| Refresh workspace + generate starter device configs | `python scripts/run.py setup` |
| Register a board (probes hardware identity, fills defaults) | `python scripts/run.py add-device <id> --address <port>` |
| Run all hardware-gated functional tests (libraries + workbench) | `python scripts/run.py test-functional` |
| Run real-board functional tests for one library | `python scripts/run.py test-libraries-functional --library timing` |
| Run real-board tests on both runtimes | `python scripts/run.py test-libraries-functional --runtime both` |
| Run real-board pytest directly (IDE play / pytest-native UX) | `pytest libraries/timing/functional_tests/` |
| Run workbench hardware-gated functional tests | `python scripts/run.py test-workbench-functional --workbench deploy` |
| Cross-runtime *unit* suite on real boards (the on-device sweep) | `python scripts/run.py test-unit-on-device` |
| On-device unit sweep, one library | `python scripts/run.py test-unit-on-device --library timing` |
| On-device unit sweep, per-file reset (256 KB boards / large suites) | `python scripts/run.py test-unit-on-device --per-file` |
| Full CI mirror + the on-device unit sweep | `python scripts/run.py preflight --with-device-unit` |
| Wipe a wedged board (last-resort) | `chumicro-workspace reset-board --device <id> --yes` |

Both `pytest libraries/<name>/functional_tests/` and `python scripts/run.py test-libraries-functional` go through the same `chumicro-pytest-device` plugin: the bare-pytest form is what IDE play buttons use, the runner form is the commit-gating wrapper. See [device-testing.md](device-testing.md) for the `--runtime` / `--deploy-mode` flag matrix.

### Docs and publishing

| What | Command |
|---|---|
| Build docs for one library | `python scripts/run.py docs --libraries timing` |
| Validate mip install against a bundle repo | `python scripts/run.py validate-mip --bundle-repo ChuMicro-Bundle-Experimental --libraries timing` |

## Where things live

| What | Where |
|---|---|
| Library source | `libraries/<name>/src/chumicro_<name>/` |
| Library host tests | `libraries/<name>/tests/` |
| Library real-board tests | `libraries/<name>/functional_tests/` |
| Library docs | `libraries/<name>/docs/` |
| Library examples | `libraries/<name>/examples/` |
| Version file | `libraries/<name>/VERSION` |
| Host-only tools | `workbench/<name>/` |
| Internal shared packages | `support/<name>/` |
| Developer task runner | `scripts/run.py` |
| Design decisions (ADRs) | `plans/decisions/` |

## When something fails

| What failed | What to do |
|---|---|
| Lint error | Run `python scripts/run.py lint`, fix the flagged lines; the error message says what's wrong |
| Test failure | Read the assertion error; the test name and line number point you right to it |
| Coverage too low | The gate is configured in `pyproject.toml` ([Decision 0025](https://github.com/ChuMicro/ChuMicro/blob/main/plans/decisions/0025-dual-coverage-thresholds.md)).  Check the `Missing` column for uncovered line numbers. If it's code you didn't write, note it in the PR. For hardware-only code that can't be tested on CPython, see [coverage exclusions](style-guide.md#coverage-exclusions) |
| `check-version` | Edit `libraries/<name>/VERSION` (patch bump is usually right) |
| `griffe warnings` | Add type annotations to function signatures |
| `functional_tests/` say no device is configured | Register a board: `python scripts/run.py add-device <id> --address <port>` (probes the board, writes `devices.yml`). No board is also fine: these tests skip cleanly. See [device testing](device-testing.md) |
| macOS CIRCUITPY drive won't mount, `diskutil list` hangs, flash-mode deploys fail | You hit the FSKit / DiskArbitration wedge.  Run `chumicro-workspace doctor --fix-fskit-wedge` (or paste the equivalent `sudo killall -9 …` chain); see [macOS CIRCUITPY troubleshooting](../troubleshooting/macos-circuitpy.md) for full detail |
| `mpremote: cp: ...: No space left on device` mid-deploy | LittleFS partition is full of stage residue from prior runs.  Wipe with `chumicro-workspace reset-board --device <id> --yes` (destructive; mkfs the filesystem).  Do NOT `diskutil unmount` CIRCUITPY drives to "clean up"; that wedges FSKit instead |
| Stuck or confused | Ask in the PR; someone will help |

**Browsing coverage in detail:** After running tests, generate an HTML report with `python -m coverage html` and open `htmlcov/index.html`. Covered lines show in green, missed lines in red; much easier than reading line numbers from the terminal. (`htmlcov/` is gitignored.)

## Links

- [Full contributing guide](https://github.com/ChuMicro/ChuMicro/blob/main/CONTRIBUTING.md)
- [Style guide](style-guide.md)
- [PR guide](pull-requests.md)
- [Device testing](device-testing.md)
- [Troubleshooting](../troubleshooting/README.md)
- [Design decisions](https://github.com/ChuMicro/ChuMicro/blob/main/plans/decisions/README.md)
