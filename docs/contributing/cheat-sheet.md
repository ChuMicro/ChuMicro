# Contributor Cheat Sheet

<img src="https://chumicro.com/assets/chumicro-head.png" alt="" align="left" width="64" style="margin-right: 16px; margin-bottom: 8px;">

Setup, the everyday commands, and the rules on one page.  The [full contributing guide](https://github.com/ChuMicro/ChuMicro/blob/main/CONTRIBUTING.md) has the detail.

<br clear="left">

## Setup (once)

Fork the repo on GitHub first, then:

```bash
git clone https://github.com/<your-username>/ChuMicro.git
cd ChuMicro
git remote add upstream https://github.com/ChuMicro/ChuMicro.git
python scripts/prepare_workspace.py                 # first-time bootstrap
source .venv/bin/activate                           # Windows: .venv\Scripts\activate
```

`prepare_workspace.py` runs on a fresh clone with no third-party packages installed.  It reuses an active venv or creates `.venv`, installs every library and tool into it, runs lint and the laptop unit tests, and ends with a `Workspace is ready` banner.

After a `git pull` that adds a library or changes dependencies, run `python scripts/run.py setup`.  It does the same install and IDE refresh against the venv you already have, and it is safe to re-run any time.

## Workflow (every change)

```bash
git checkout main && git pull upstream main && git push origin main
git checkout -b fix/my-change
# ... make changes ...
pytest libraries/<name>/tests/        # fast check while you work
python scripts/run.py preflight       # last line must start "Preflight passed."
git add <changed files> && git commit # imperative subject, body says why
git push -u origin fix/my-change      # then open the PR on GitHub
```

*Preflight* runs every check CI runs on a pull request: lint, unit tests on CPython, MicroPython, and CircuitPython, the docs build, example and demo checks, and the size and version checks.

## The rules

1. **Run preflight before every commit**, docs-only commits included.  When it passes, the required CI checks should pass too.
2. **Use descriptive names.** The linter names the exact replacement, so each hit is mechanical; expect a few in your first PR. Single-letter loop targets (`for i in range(10)`) are fine. ([Decision 0022](https://github.com/ChuMicro/ChuMicro/blob/main/plans/decisions/0022-naming-conventions.md))
3. **No `async`/`await`.** Library code takes turns in one shared loop: long-running services through `check()`/`handle()`, step-by-step flows as generators passed to `runner.add_generator`.  CircuitPython's asyncio has a broken stream layer, and every `await` there allocates.  Lint enforces it. ([Decision 0087](https://github.com/ChuMicro/ChuMicro/blob/main/plans/decisions/0087-generators-for-sequential-io.md))
4. **Accept dependencies as constructor parameters.** Don't import `board` or `busio` at the top level of library code.  That is what lets tests run on a laptop with no hardware.
5. **Tests live next to the code.** `libraries/<name>/tests/`. Run them with `pytest libraries/<name>/tests/`.
6. **Bump `VERSION` once per PR when users would see a change.** Edit `libraries/<name>/VERSION`: patch for a fix or a changed message, minor for a feature or a breaking change (every package is below 1.0).  Tests, docs, examples, and docstring-only edits need no bump.  Preflight's `check-version` catches a missing one.
7. **Docstrings are required** on public functions. Types go on the signature, descriptions in the docstring.
8. **f-strings everywhere.** No `%` formatting, no `.format()`.
9. **Examples never exit.** An example does its one-shot part, then keeps working on a timer inside a top-level `while True:` loop.  See [Writing an example](https://github.com/ChuMicro/ChuMicro/blob/main/CONTRIBUTING.md#writing-an-example).
10. **`const()` and `memoryview` are optional on day one.** Write the clear version first; optimize when a measurement says so.
11. **Update the docs your change made wrong, in the same PR.** A renamed function means its README, guide, and examples change too.

## Common commands

Preflight is the one command you have to remember; everything else is reference.

### Every PR

| What | Command |
|---|---|
| Run everything CI will run | `python scripts/run.py preflight` |
| Lint only (ruff plus the project's own rules) | `python scripts/run.py lint` |
| Scaffold a new device library | `python scripts/run.py new-library my_sensor` |
| Scaffold a laptop-only workbench tool | `python scripts/run.py new-library --workbench my_tool` |

### Testing

| What | Command |
|---|---|
| Test one library | `pytest libraries/timing/tests/` |
| Filter by test name | `pytest libraries/timing/tests/ -k deadline` |
| Stop on first failure, verbose | `pytest libraries/timing/tests/ -k deadline -x -v` |
| Test a single file | `pytest libraries/timing/tests/test_deadline.py` |
| Changed libraries, with the coverage gate | `python scripts/run.py test` |
| Every package, with the coverage gate | `python scripts/run.py test --all` |
| One library, with the coverage gate | `python scripts/run.py test --libraries timing` |
| One test, through the gated runner | `python scripts/run.py test -k timing/test_deadline/rate_fires --no-cov` |
| Test the `scripts/` tooling itself | `python scripts/run.py test-scripts` |
| Check examples parse and import | `python scripts/run.py verify-examples --libraries timing` |

Bare `pytest` is the everyday command for iteration and what IDE play buttons run.  `python scripts/run.py test` runs each library's tests in its own pytest process and enforces the coverage gate ([Decision 0009](https://github.com/ChuMicro/ChuMicro/blob/main/plans/decisions/0009-per-library-test-runs.md)); preflight runs it for you.

### Cross-runtime testing

The MicroPython and CircuitPython *unix ports* are desktop builds of each runtime.  Running the unit suite under them catches code that works on CPython and breaks on a board.

| What | Command |
|---|---|
| Build the MicroPython unix port (once, slow) | `python scripts/run.py prepare-micropython` |
| Build the CircuitPython unix port (once, slow) | `python scripts/run.py prepare-circuitpython` |
| Build only the `mpy-cross` compilers | `python scripts/run.py prepare-mpy-cross` |
| Unit tests on the MicroPython unix port | `pytest libraries/ --target unix-port --runtime micropython` |
| Unit tests on the CircuitPython unix port | `pytest libraries/ --target unix-port --runtime circuitpython` |
| Unit tests on both unix ports | `pytest libraries/ --target unix-port --runtime both` |
| One file on one unix port | `pytest libraries/timing/tests/test_deadline.py --target unix-port --runtime micropython` |
| Unit tests on CPython and both unix ports | `python scripts/run.py test-all-runtimes --libraries timing` |

### Device testing

A *functional test* lives in `libraries/<name>/functional_tests/` and runs on a real board.  Without a registered board these tests skip.

| What | Command |
|---|---|
| Register a board (probes it, writes `devices.yml`) | `python scripts/run.py add-device <id> --address <port>` |
| Functional tests for one library | `python scripts/run.py test-libraries-functional --library timing` |
| Functional tests on both runtimes | `python scripts/run.py test-libraries-functional --runtime both` |
| Functional tests through bare pytest (IDE play buttons) | `pytest libraries/timing/functional_tests/` |
| Every hardware test (libraries, then workbench tools) | `python scripts/run.py test-functional` |
| Hardware tests for one workbench tool | `python scripts/run.py test-workbench-functional --workbench deploy` |
| Unit suite on real boards (the on-device sweep) | `python scripts/run.py test-unit-on-device` |
| On-device sweep, one library | `python scripts/run.py test-unit-on-device --library timing` |
| On-device sweep, fresh interpreter per file (256 KB boards) | `python scripts/run.py test-unit-on-device --per-file` |
| Preflight plus the functional tests | `python scripts/run.py preflight --with-functional` |
| Preflight plus the on-device sweep | `python scripts/run.py preflight --with-device-unit` |
| Run one example on a board | `chumicro-workspace deploy-example timing rate_blink` |
| List every example | `chumicro-workspace deploy-example --list` |
| Wipe a wedged board (last resort, erases its files) | `chumicro-workspace reset-board --device <id> --yes` |

`pytest libraries/<name>/functional_tests/` and `python scripts/run.py test-libraries-functional` both run through the `chumicro-pytest-device` plugin.  IDE play buttons use the bare-pytest form.  See [device-testing.md](device-testing.md) for the `--runtime` and `--deploy-mode` flags.

### Docs and publishing

| What | Command |
|---|---|
| Build docs for one library | `python scripts/run.py docs --libraries timing` |
| Preview one library's docs with live reload | `python scripts/run.py docs --libraries timing --serve` |
| Validate a `mip` install against a bundle repo | `python scripts/run.py validate-mip --bundle-repo ChuMicro-Bundle-Experimental --libraries timing` |

## Where things live

| What | Where |
|---|---|
| Library source | `libraries/<name>/src/chumicro_<name>/` |
| Library laptop tests | `libraries/<name>/tests/` |
| Library real-board tests | `libraries/<name>/functional_tests/` |
| Library docs | `libraries/<name>/docs/` |
| Library examples | `libraries/<name>/examples/` |
| Version file | `libraries/<name>/VERSION` |
| Multi-library demos | `demos/<name>/` |
| Laptop-only tools (deploy, REPL, lint rules) | `workbench/<name>/` |
| Shared helpers (test harness, docs artwork) | `support/<name>/` |
| Task runner | `scripts/run.py` |
| Design decisions (ADRs) | `plans/decisions/` |

## When something fails

| What failed | What to do |
|---|---|
| Lint error | Run `python scripts/run.py lint` and fix the flagged lines; each message says what's wrong |
| Test failure | Read the assertion error; the test name and line number point you to it |
| Coverage too low | The root `pyproject.toml` sets the 85 % gate ([Decision 0025](https://github.com/ChuMicro/ChuMicro/blob/main/plans/decisions/0025-dual-coverage-thresholds.md)).  The `Missing` column lists uncovered line numbers. If it's code you didn't write, note it in the PR. For code that only runs on a board, see [coverage exclusions](style-guide.md#coverage-exclusions) |
| `check-version` | Edit `libraries/<name>/VERSION` (a patch bump is usually right) |
| `griffe warnings` | Add type annotations to function signatures |
| `functional_tests/` say no device is configured | Register a board: `python scripts/run.py add-device <id> --address <port>`.  No board is fine too: these tests skip. See [device testing](device-testing.md) |
| macOS CIRCUITPY drive won't mount, `diskutil list` hangs, flash-mode deploys fail | macOS's file-system service (FSKit) has wedged.  Run `chumicro-workspace doctor --fix-fskit-wedge`; [macOS CIRCUITPY troubleshooting](../troubleshooting/macos-circuitpy.md) has the detail |
| `mpremote: cp: ...: No space left on device` mid-deploy | The board's filesystem is full of files from earlier test runs.  Wipe it with `chumicro-workspace reset-board --device <id> --yes`, which erases every file on the board.  Never `diskutil unmount` a CIRCUITPY drive to clean up; that wedges FSKit instead |
| Stuck or confused | Ask in the PR; someone will help |

**Browsing coverage in detail:** after `python scripts/run.py test`, run `python -m coverage html` and open `htmlcov/index.html`.  Covered lines show green and missed lines red, which beats reading line numbers in the terminal.  (`htmlcov/` is gitignored.)

## Links

- [Full contributing guide](https://github.com/ChuMicro/ChuMicro/blob/main/CONTRIBUTING.md)
- [Style guide](style-guide.md)
- [PR guide](pull-requests.md)
- [Device testing](device-testing.md)
- [Releases and promotion](releases.md)
- [Troubleshooting](../troubleshooting/README.md)
- [Design decisions](https://github.com/ChuMicro/ChuMicro/blob/main/plans/decisions/README.md)
