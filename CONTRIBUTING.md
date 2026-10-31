# Contributing to ChuMicro

<img src="support/docs/chumicro_tip.png" align="left" width="64" style="margin-right: 16px; margin-bottom: 8px;">

Thanks for your interest in ChuMicro, a family of Python libraries that run unmodified on CircuitPython, MicroPython, and CPython.

Writing code is one way to contribute among several.  Using the libraries and telling us what happened counts.  So does reporting a confusing error message, asking a question that exposes a documentation gap, or running an example on a board we haven't tried.  If you do want to change code, this page walks the whole path from clone to merged pull request.  One command sets up your environment, and one command runs every check CI will run.

<br clear="left">

> ⚡ **Short on time?**  The **[Contributor Cheat Sheet](docs/contributing/cheat-sheet.md)** is one page: setup, the everyday commands, and the one command to run before committing.

## Finding your way around

| What you want to do | Read this |
|---|---|
| Get the short version | [Contributor Cheat Sheet](docs/contributing/cheat-sheet.md) |
| Find something to work on | [Good first contributions](#good-first-contributions) below |
| Set up your environment | [Setting up](#setting-up) below |
| Configure your editor | [PyCharm](docs/contributing/development-pycharm.md), [VS Code](docs/contributing/development-vscode.md), or [other editors](docs/contributing/development-other-editors.md) |
| Make your first change, end to end | [Your first change](#your-first-change-a-worked-example) below |
| Write or fix an example | [Writing an example](#writing-an-example) below |
| Understand the test layers | [Testing](#testing) below |
| Run tests on a real board | [Device Testing](docs/contributing/device-testing.md) |
| Understand `devices.yml` / `workspace.yml` / `secrets.toml` | [Workspace, devices, and secrets](docs/contributing/config-files.md) |
| Learn the code style | [Style Guide](docs/contributing/style-guide.md) |
| Open a pull request | [Creating a Pull Request](docs/contributing/pull-requests.md) |
| Know when to bump `VERSION` | [VERSION bumps](#version-bumps) below, then [Releases and Promotion](docs/contributing/releases.md) |
| Add a new library | [Adding a New Library](docs/contributing/new-library.md) |
| Adopt one library into an existing codebase | [Standalone integration](docs/contributing/standalone-integration.md), then [Slimming your deploy](docs/contributing/slimming-your-deploy.md) |
| Add a host-only tool | [Adding a Workbench Package](docs/contributing/workbench.md) |
| Work with an AI coding agent | [Working with Agents](docs/contributing/working-with-agents.md), plus the [agent style guide](docs/contributing/agent-style-guide.md) for prose tone |
| Maintain the repository itself | [Maintainer Runbook](docs/contributing/maintainers.md) |
| Recover from a broken state | [Troubleshooting](docs/troubleshooting/) |

Each page stands on its own.  Read the ones that match what you're doing and skip the rest.

## What you're contributing to

The repository holds a few kinds of code, each in its own top-level folder:

| Folder | What lives there |
|---|---|
| `libraries/` | The device libraries: the code that runs on your board.  Each library keeps its source, tests, examples, and docs together in `libraries/<name>/`. |
| `libraries/<name>/examples/` | Short programs that show one library at work.  An example is what most people copy onto a board first. |
| `demos/` | Bigger programs that show several libraries working together, each with a host-side script that deploys it and checks the result. |
| `workbench/` | Laptop-only tools: the deploy CLI, the serial REPL, the pytest plugin that runs tests on a board, and the lint rules.  They never run on a board. |
| `support/` | Shared helpers for the other trees: the test harness that runs library tests on all three runtimes, and the docs site artwork. |
| `scripts/` | The task runner (`scripts/run.py`) that builds, lints, and tests everything. |
| `plans/` | Design decisions and the work queue. |

A few things about the project's shape are worth knowing before you edit:

- **Code lands on three runtimes.**  Library code runs on boards that may have 256 KB of RAM and no `typing` module.  You don't set up the cross-runtime builds yourself; the tooling tests every library on all three runtimes.  That constraint explains some style rules you'll meet below.
- **Nothing blocks.**  Libraries do their work in small steps inside a loop that every part of the program shares.  No `async`/`await`, no threads.  [Why the code looks the way it does](#why-the-code-looks-the-way-it-does) has the reasoning.
- **Most changes touch one library.**  Features that span libraries land easier as a sequence of per-library PRs than as one large change.
- **Real hardware is optional.**  Fixing a bug, adding tests, or improving docs needs no microcontroller.  A board only enters the picture for on-board tests and for trying examples.

## Good first contributions

Real ways in that don't require knowing the codebase deeply:

- **Fix a typo or clarify a sentence** in any README, guide, or docstring.  For these you can skip local setup: edit the file in GitHub's web UI (the pencil icon) and GitHub forks the repo and opens the PR for you.
- **Add or improve an example** in a library's `examples/` folder.  Pick something the library's guide explains but doesn't show, and follow [Writing an example](#writing-an-example).
- **Improve test coverage.**  Run one library's tests, look at the uncovered lines, write tests for them.
- **Run a library on your board and say what happened.**  "Worked on my ESP32-S3" is useful on its own.  Use the [board test report](https://github.com/ChuMicro/ChuMicro/issues/new?template=board_test_report.yml) template.

Browse [open issues](https://github.com/ChuMicro/ChuMicro/issues) and [discussions](https://github.com/ChuMicro/ChuMicro/discussions) for what people are working on; smaller items make easier first PRs.

## Prerequisites

- **Python 3.11 or newer.**  The laptop-side tooling needs it.  macOS: `brew install python`; Linux: your system package; Windows: [python.org](https://python.org).
- **Git**, any recent version.  You need clone, branch, commit, and push.
- **Any editor.**  The project ships ready-made configurations for PyCharm and VS Code.  Neovim, Zed, Emacs, and Sublime work too; [other editors](docs/contributing/development-other-editors.md) covers pointing any Pyright- or venv-aware editor at the workspace.

**Windows users:** edit, lint, and run unit tests natively, and use WSL2 for the cross-runtime checks.  The MicroPython and CircuitPython desktop builds compile under WSL2 and do not build on native Windows.  CI runs every check on your PR either way.

## Setting up

First-time setup takes about five minutes once Python is installed, and it's safe to re-run if anything goes wrong.

**1. Fork and clone.**  Click **Fork** on the [ChuMicro repository](https://github.com/ChuMicro/ChuMicro), then:

```bash
git clone https://github.com/<your-username>/ChuMicro.git
cd ChuMicro
git remote add upstream https://github.com/ChuMicro/ChuMicro.git
```

You now push to your fork (`origin`) and pull updates from the original (`upstream`).

**2. Bootstrap.**

```bash
python scripts/prepare_workspace.py
```

This creates a `.venv/` virtual environment, installs every library and tool into it in editable mode (so your edits take effect without reinstalling), generates IDE configs, and runs lint plus the laptop unit tests to confirm the install worked.  It ends with a `Workspace is ready` banner.  It uses [`uv`](https://docs.astral.sh/uv/) when available and the stdlib `venv` otherwise.  Prefer your own environment (pyenv, conda, an existing venv)?  Activate it and run `python scripts/run.py setup` instead.

**3. Activate the venv** in every new terminal:

```bash
source .venv/bin/activate        # Windows: .venv\Scripts\activate
```

(Or skip activation and call `.venv/bin/python` directly.)

**4. Run preflight.**

```bash
python scripts/run.py preflight
```

Preflight is the project's full check: lint, every library's unit tests on CPython, MicroPython, and CircuitPython, the docs build, the example and demo checks, and the size and version checks.  CI runs the same command on every pull request.  The first run also builds the MicroPython and CircuitPython desktop runtimes it tests against, which adds a few minutes; later runs reuse them and finish in a minute or two.  When the last line starts with `Preflight passed.`, you're set.  If it fails, the output names the failing step.

**5. Open your editor** at the project root.  PyCharm and VS Code pick up committed configurations ([PyCharm notes](docs/contributing/development-pycharm.md), [VS Code notes](docs/contributing/development-vscode.md)).  For anything else, [other editors](docs/contributing/development-other-editors.md) covers the two things that matter: use the venv's interpreter, and point Pyright at `pyrightconfig.json` in the root.  Either way, imports like `from chumicro_timing import ticks_ms` should resolve without red underlines.  If they don't, run `python scripts/run.py sync-ide` and reload the editor.

## The development loop

Day to day, the loop is short:

1. **Edit** a library file.  Installs are editable, so changes take effect immediately.
2. **Run that library's tests** while you iterate.  `pytest libraries/timing/tests/` takes a few seconds, and IDE play buttons work.
3. **Run preflight before every commit**, docs-only commits included.  A docs change can still break the docs build or an example check.

```bash
python scripts/run.py preflight
```

Preflight takes a minute or two, so save it for the commit and use focused pytest runs while iterating.  A green preflight is the bar for opening a PR.  Two CI checks have no local preflight phase: the unit tests on Python 3.11, 3.12, and 3.13, and the check that MicroPython can install and import every library's compiled `.mpy` form.  [Creating a Pull Request § CI checks](docs/contributing/pull-requests.md#ci-checks) shows how to reproduce those.  Anything else that fails in CI after a green local preflight is a tooling bug worth filing.

On native Windows, where the MicroPython and CircuitPython phases need WSL2, run what you can locally and let CI cover the rest.

**Reading a failure.**  Preflight runs its phases in parallel and prints a `Phase summary:` table with `PASS` or `FAIL` beside each phase.  It ends with `Preflight failed at: <phase>`, just below the last lines of that phase's output.  The failures you're most likely to meet:

- **`test` fails on coverage.**  Your change added lines the tests don't exercise; the `Missing` column lists them.  Lines only reachable on a real board can be marked `# pragma: no cover` ([Style Guide § Coverage exclusions](docs/contributing/style-guide.md#coverage-exclusions)).  If coverage fails on code you didn't touch, note it in the PR and a maintainer will help.
- **`lint` fails.**  Each message names the file, the line, and what to change.  Lint runs ruff plus the project's own rules (`chumicro-checks`), and the naming rule's message spells out the exact rename.
- **`docs` fails with griffe warnings.**  A docstring problem, usually a missing type annotation or a malformed `Args:` section.
- **`check-version` fails.**  You changed a library's code without bumping its `VERSION` file.  See [VERSION bumps](#version-bumps).
- **`test-micropython` or `test-circuitpython` fails.**  The code passes on CPython and fails on a board runtime.  Reproduce with `pytest libraries/<name>/tests --target unix-port --runtime micropython` (or `circuitpython`).  Usual culprits: a `typing` or `__future__` import (absent on boards) and relative imports in library code.
- **`check-size` fails.**  The library's compiled size grew past its ceiling in `size-budgets.toml`.  Say so in the PR; a maintainer decides whether the growth earns a bigger budget.

## Your first change: a worked example

This walkthrough uses a docstring clarification as the task.  Substitute your own change; the steps are identical.

**Pick something small.**  A confusing docstring, a typo, a one-line fix.  Small PRs review faster and merge sooner.

**Branch off main:**

```bash
git checkout main
git pull upstream main
git checkout -b fix/clarify-rate-docstring
```

Name branches `fix/…`, `docs/…`, or `feature/…` to signal intent.  Every PR targets `main`.

**Edit, then test the library you touched:**

```bash
pytest libraries/timing/tests/
```

The [cheat sheet](docs/contributing/cheat-sheet.md#testing) has the focused variants (`-k` filters, stop on first failure, one file) for tighter loops.

**Run preflight, then commit:**

```bash
python scripts/run.py preflight
git add libraries/timing/src/chumicro_timing/deadline.py
git commit
```

Stage the files you changed by name rather than `git add -A`, so stray files in your tree stay out of the commit.  Git opens your editor for the message.  Write an imperative subject and a body that explains *why*; the diff already shows *what*:

```
Say that Rate fires when due() is called, not on a clock

The Rate docstring read as if Rate fired on its own timer.  It fires
only when due() runs and sees that a period has passed, so a main loop
that rarely calls due() sees late fires.  Users debugging "why didn't
my timer fire?" need to know that.
```

A docstring-only change like this one needs no `VERSION` bump.

**Push and open the PR:**

```bash
git push -u origin fix/clarify-rate-docstring
```

Click the "Compare & pull request" banner GitHub offers, check that the base is **ChuMicro/ChuMicro** `main` (not your own fork), and fill in the PR template.

**Then CI and review.**  CI runs on the PR automatically.  GitHub holds a first-time contributor's runs until a maintainer approves them, so your first PR's checks may sit at "waiting" for a while.  If something fails, fix it locally and push to the same branch; CI re-runs.  A maintainer reviews and may ask for changes; push fixes to the same branch and the PR updates.  Expect review comments even on a green PR: automation checks that the code is sound, and review covers what automation can't judge, like naming, scope, and API shape.

After the merge, your change is on `main`.  If you bumped a `VERSION` file, an experimental release publishes automatically ([Releases and Promotion](docs/contributing/releases.md)); otherwise your change ships with the library's next release.

**Keeping your fork in sync** for the next change:

```bash
git checkout main
git pull upstream main
git push origin main
```

If `main` moves while your PR is open and you need its commits, rebase your branch onto it (`git rebase main`, then `git push --force-with-lease`).  The project keeps history linear, so rebase rather than merging `main` into your branch.

## Commit messages

Write an imperative subject that fits on one line (aim for 70 characters) and a body that explains why.  When a decision record in `plans/decisions/` drove the change, name it in the body.

PRs land as one squashed commit, and the PR title becomes that commit's subject on `main`, so give the PR title the same care.  Recent subjects on `main` read like this:

```
Credit Adafruit_CircuitPython_Ticks in the ticks module
Fix the artwork that 404s on every contributing page
Move the documentation to chumicro.com
```

Two house rules:

- **No `Co-Authored-By:` trailers**, AI-agent ones included.  Commits are authored by the person running the work.
- **Stage files by name**, never `git add -A` or `git add .`, so unrelated changes in your tree stay out.

Full PR conventions: [Creating a Pull Request](docs/contributing/pull-requests.md).

## VERSION bumps

Each library and tool has its own `VERSION` file and follows [semantic versioning](https://semver.org/).  Bump it once per PR when the PR changes what a user of that package gets:

- **Patch** (`0.8.4` to `0.8.5`) for a bug fix or any behavior change, including a changed error message or other string the package ships.
- **Minor** (`0.8.4` to `0.9.0`) for a new feature.  Every package is below 1.0, so a breaking change (a removed or renamed public function) is a minor bump too.
- **No bump** for tests, docs, examples, or a code change limited to comments and docstrings.

One bump covers the whole PR, however many commits it has.  `check-version` in preflight tells you when a bump is missing, and `check-api` names the minimum level when you removed or renamed something public.

Before 1.0 the project keeps no backwards-compatibility shims: when you rename something, rename it everywhere in the same PR rather than leaving an alias or a deprecation warning behind.

Merging a bumped `VERSION` publishes an experimental release automatically; promotion to stable is a separate maintainer step.  [Releases and Promotion](docs/contributing/releases.md) has the full rules.

## How changes land

Every change reaches `main` the same way, whether it comes from a first-time contributor or from the maintainer: a branch, a pull request, green checks, a squash merge.  The branch ruleset blocks direct pushes to `main` for everyone, maintainer included.

A merge needs these checks green:

- **preflight**, the same 13-phase run `python scripts/run.py preflight` does locally
- **compatibility**, the unit tests on Python 3.11, 3.12, and 3.13
- **Validate mpy bytecode**, which compiles every library to `.mpy` and proves MicroPython can install and import it

A squashed PR reads best when it does one thing.  The maintainer ([@ChuxMaker](https://github.com/ChuxMaker)) reviews and merges.  ChuMicro has one maintainer, so allow a few days for review; a polite follow-up after a week of silence is welcome.

The maintainer can also ask an AI reviewer for a first pass by commenting `@claude /review` on the PR.  Its comments are advisory: the maintainer decides what matters, and you can push back on its findings as you would with a human reviewer.  Only maintainers can summon it, so the command does nothing from a contributor's account.

This project follows the [Contributor Covenant](CODE_OF_CONDUCT.md).  The short version: be decent to each other.

## Testing

ChuMicro tests at four layers.  Each catches a different kind of bug.  You'll mostly use the first.

**1. Unit tests on your laptop.**  Each library's `tests/` folder, plain pytest, seconds to run.  Tests build the object under test with fakes plugged in for anything that would need hardware.  Libraries that talk to hardware ship their fakes in a `testing` module (`from chumicro_timing.testing import FakeTicks`), so you rarely write a mock by hand.

```bash
pytest libraries/timing/tests/               # one library
pytest libraries/                            # every library
pytest libraries/ -k test_name_filter        # filter by test name
```

`python scripts/run.py test` runs the same tests with each library's coverage gate (changed libraries by default, `--all` for everything).  Use bare pytest while iterating; preflight runs the gated form for you.

**2. The same tests on the board runtimes.**  MicroPython and CircuitPython each publish a desktop build, called a *unix port*, that runs on your laptop.  The whole unit suite runs under both, which catches "works on CPython, breaks on the board" without a board:

```bash
pytest libraries/ --target unix-port --runtime both
```

The first run needs the binaries built once: `python scripts/run.py prepare-micropython` and `python scripts/run.py prepare-circuitpython` (a few minutes each, reused after that).  Preflight runs this layer too.

**3. Functional tests on a real board.**  A *functional test* proves behavior a fake can't model: USB timing, filesystem semantics, radio state.  These live in `functional_tests/` folders and run *inside the board's Python*.  Pytest copies the test onto a connected board, runs it there, and reports back like any other test.

```bash
pytest libraries/timing/functional_tests/
```

You need a registered board (`python scripts/run.py add-device`); without one these tests skip, which is the expected result on a laptop with nothing plugged in.  Setup, multi-board runs, and the PR-summary output live in [Device Testing](docs/contributing/device-testing.md).  Write a functional test only when injected fakes can't prove the behavior.

**4. Examples on real hardware.**  Preflight checks that every example parses and its imports resolve.  Deploying one (`chumicro-workspace deploy-example timing rate_blink`) and watching its output is the manual check that the documented quickstart still works.  Reach for it when you change an API an example uses.

## Writing an example

An example is the first ChuMicro code most people run, usually by copying it onto a board as `code.py`.  Write it for someone who knows CircuitPython or MicroPython from Adafruit Learn guides or Arduino sketches and has never seen this project:

- **It never ends.**  A board program runs until the power goes, and every sketch that reader has seen ends in a loop.  Do the one-shot part first (connect to wifi, send the first request, print the result), then keep doing visible work on a timer: blink an LED, print a reading every second, repeat the request every ten seconds.  No `sys.exit()`, no `raise SystemExit`, and no falling off the end of the file.
- **The loop is on the page.**  The file ends in a `while True:` at the top level, not tucked inside a `main()` function.  When the example uses `chumicro_runner`, the loop reads `now_ms = runner.tick()` then `runner.wait(now_ms)`; `runner.run_until(...)` hides that loop from the reader.  Lint flags an example that exits or never reaches its loop.
- **It imports public packages only**: ChuMicro libraries plus the board's own modules (`board`, `digitalio`, `machine`).  No test harness, no workbench tools, no `if __name__ == "__main__":` guard.
- **Board-specific examples say so.**  Name the file `circuitpython_<name>.py` or `micropython_<name>.py` and set `__chumicro_runtimes__ = ("circuitpython",)` (or `"micropython"`) at the top.
- **The docstring says what you'll see**, with real output pasted in.

[`libraries/timing/examples/rate_blink.py`](libraries/timing/examples/rate_blink.py) is a complete small one.  Check yours with `python scripts/run.py verify-examples --libraries timing` (syntax and imports), then run it on a board with `chumicro-workspace deploy-example timing rate_blink`.

Demos follow the same never-exit rule and a few more; [demos/README.md § Adding a demo](demos/README.md#adding-a-demo) has them.

## Adding a new package

```bash
python scripts/run.py new-library my_sensor              # a device library
python scripts/run.py new-library --workbench my_tool    # a laptop-only tool
```

Both scaffold a working starter (tests pass, lint is clean, the example runs) that you replace with your implementation.  Before scaffolding, skim [Adding a New Library § Before you start](docs/contributing/new-library.md#before-you-start): a two-minute check that your idea isn't already in flight, already decided against, or better shaped as part of an existing library.

## Why the code looks the way it does

Some rules here differ from general-Python instinct.  Each exists because of a real constraint (RAM measured in KB, three runtimes with different gaps, debugging over a serial cable), and each has a decision record in [`plans/decisions/`](plans/decisions/) with the full reasoning.  The short versions:

**A shared loop instead of `async`/`await`.**  A long-running piece of a program, such as the wifi connection or an MQTT client, is a *service* with two methods: `check(now_ms)` ("do I have work?") and `handle(now_ms)` ("do one piece of it").  The runner gives each service a turn on every pass of the loop.  Step-by-step flows are written as generators (`yield from`) that the runner drives.  Both shapes keep every pause visible: readable in a serial traceback, steppable in a debugger.  `async` machinery differs per runtime and is incomplete on CircuitPython, so `async`, `await`, and asyncio itself are banned in library code, and lint enforces it.  ([Decision 0014](plans/decisions/0014-runner-pattern.md), [Decision 0087](plans/decisions/0087-generators-for-sequential-io.md))

**Dependencies come in through the constructor.**  Libraries never import `board`, `busio`, or a socket module at the top level.  A socket, an I2C bus, or a clock arrives as a constructor argument with a default that loads only when needed.  That is why laptop tests can plug in fakes and run in milliseconds.  ([Decision 0010](plans/decisions/0010-library-testability.md))

**Descriptive names, even for short-lived variables.**  A bare `result = t.get(k)` three screens from where `t` was bound makes the next reader reconstruct context the name could have carried.  The linter flags single letters and a short list of banned abbreviations, and its message names the exact rename, so each hit is mechanical.  If you've written Python for years this rule will fight your habits; [Decision 0022](plans/decisions/0022-naming-conventions.md) explains why the project pays that cost.

**Memory tricks wait for a measurement.**  Pre-allocated buffers and `memoryview` windows matter on a small heap, and they make simple code harder to read.  Write the clear version first; [Style Guide § Memory patterns](docs/contributing/style-guide.md#memory-patterns-library-code-only) has the cookbook for when a measurement says it's time.

## When you're stuck

Most stuck moments resolve at one of these:

- **Imports show unresolved in the editor.**  Confirm the venv is active (`which python` points into `.venv/`), run `python scripts/run.py sync-ide`, reload the editor window.
- **Tests pass locally, fail in CI.**  Run full preflight (your local run may have covered one library).  If the failure is under MicroPython or CircuitPython, reproduce with `--target unix-port --runtime <micropython|circuitpython>`.  Check `git status` for a file you forgot to commit.
- **`prepare_workspace.py` fails on a fresh clone.**  Check that `python --version` is 3.11 or newer, and delete any half-built `.venv/` from an aborted run before retrying.

When nothing matches: open a [Discussion](https://github.com/ChuMicro/ChuMicro/discussions) for questions, a [bug report](https://github.com/ChuMicro/ChuMicro/issues/new?template=bug_report.yml) for something broken, or a [feature request](https://github.com/ChuMicro/ChuMicro/issues/new?template=feature_request.yml) for an idea.  Ask early; an hour spent stuck helps nobody.

## Common mistakes

| Symptom | What's going on | Fix |
|---|---|---|
| `pytest` passes but preflight fails coverage | Bare pytest doesn't enforce the coverage gate | Preflight's output lists the uncovered lines; add tests for them |
| `functional_tests/` says no device configured | No board registered in `devices.yml` yet | `python scripts/run.py add-device`; see [Device Testing](docs/contributing/device-testing.md) |
| `check-version` fails but you only changed tests | It watches `src/` and `pyproject.toml` | Tests, docs, and examples need no bump; recheck which files your branch changed with `git diff --stat main` |
| `griffe warnings` in the docs build | Missing type annotation on a signature | Annotate the signature; the docstring carries descriptions |
| Editor shows red import underlines | Stale IDE config | `python scripts/run.py sync-ide`, reload the editor |
| Merge conflicts after pushing | `main` moved under you | Rebase onto the latest `main` |

## Going deeper

Once the basic loop feels comfortable:

- **[`plans/decisions/`](plans/decisions/)**: every structural decision has a record of what was decided and why.  Search here before proposing a structural change; your idea may have a history.
- **Proposing a design change:** open a [Discussion](https://github.com/ChuMicro/ChuMicro/discussions) describing the problem and the tradeoff you see, and reference any decision records it touches.  If it holds up, a maintainer works with you to land it as a new numbered record in `plans/decisions/` alongside the code change.
- **[`AGENTS.md`](AGENTS.md)**: the AI-agent operating manual.  It states every rule on this page in its strictest form, so it doubles as a reference for humans.
- **[Workspace template](https://github.com/ChuMicro/ChuMicro-Workbench-Template)**: the starter repo for projects built *on* ChuMicro.  Reading it shows how a downstream user assembles the libraries into an application.

## License

By contributing, you agree your contributions will be licensed under the [MIT License](LICENSE).
