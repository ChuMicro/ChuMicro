# Contributing to ChuMicro

<img src="support/docs/chumicro_tip.png" align="left" width="64" style="margin-right: 16px; margin-bottom: 8px;">

ChuMicro is a family of Python libraries that run unmodified on CircuitPython, MicroPython, and CPython.

Code is one way to contribute. A report of what happened when you used a library counts too, and so does a confusing error message, a question that exposes a gap in the docs, or an example run on a board nobody has tried yet.

<br clear="left">

## Finding your way around

| What you want to do | Read this |
|---|---|
| Look up a command | [Contributor Cheat Sheet](docs/contributing/cheat-sheet.md) |
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
| Know when to bump `VERSION` | [Releases and Promotion § When to bump VERSION](docs/contributing/releases.md#when-to-bump-version) |
| Add a new library | [Adding a New Library](docs/contributing/new-library.md) |
| Adopt one library into an existing codebase | [Standalone integration](docs/contributing/standalone-integration.md), then [Slimming your deploy](docs/contributing/slimming-your-deploy.md) |
| Add a host-only tool | [Adding a Workbench Package](docs/contributing/workbench.md) |
| Work with an AI coding agent | [Working with Agents](docs/contributing/working-with-agents.md), plus the [agent style guide](docs/contributing/agent-style-guide.md) for prose tone |
| Maintain the repository itself | [Maintainer Runbook](docs/contributing/maintainers.md) |
| Recover from a broken state | [Troubleshooting](docs/troubleshooting/) |

## What you're contributing to

Each kind of code has its own top-level folder:

| Folder | What lives there |
|---|---|
| `libraries/` | The device libraries: the code that runs on your board.  Each library keeps its source, tests, examples, and docs together in `libraries/<name>/`. |
| `libraries/<name>/examples/` | Short programs that show one library at work.  An example is what most people copy onto a board first. |
| `demos/` | Bigger programs that show several libraries working together, each with a host-side script that deploys it and checks the result. |
| `workbench/` | Laptop-only tools: the deploy CLI, the serial REPL, the pytest plugin that runs tests on a board, and the lint rules.  They never run on a board. |
| `support/` | Shared helpers for the other trees: the test harness that runs library tests on all three runtimes, and the docs site artwork. |
| `scripts/` | The task runner (`scripts/run.py`) that builds, lints, and tests everything. |
| `plans/` | Design decisions and the work queue. |

- **Library code runs on three runtimes.**  A board may have 256 KB of RAM and no `typing` module.  Preflight tests every library on CPython, MicroPython, and CircuitPython.
- **A pull request does one thing.**  A feature that spans libraries lands more easily as one pull request per library.
- **A board is optional.**  Fixing a bug, adding tests, or improving docs needs no microcontroller.  A board comes in for on-board tests and for trying examples.

## Good first contributions

- **Fix a typo or clarify a sentence** in any README, guide, or docstring.  GitHub's web editor, the pencil icon on any file, forks the repository and opens the pull request for you, with no local setup.  CI runs preflight on that pull request.
- **Add or improve an example** in a library's `examples/` folder.  Pick something the library's guide explains and leaves unshown, and follow [Writing an example](#writing-an-example).
- **Improve test coverage.**  Run one library's tests, look at the uncovered lines, and write tests for them.
- **Run a library on your board and say what happened.**  "Worked on my ESP32-S3" is useful on its own.  Use the [board test report](https://github.com/ChuMicro/ChuMicro/issues/new?template=board_test_report.yml) template.

[Open issues](https://github.com/ChuMicro/ChuMicro/issues) and [discussions](https://github.com/ChuMicro/ChuMicro/discussions) show what people are working on.  Smaller items make easier first pull requests.

## Prerequisites

- **Python 3.11 or newer** for the laptop-side tooling.  Install it with `brew install python` on macOS, your system package on Linux, or the installer from [python.org](https://python.org) on Windows.
- **Git**, any recent version, for clone, branch, commit, and push.
- **Any editor.**  The project ships ready-made configurations for PyCharm and VS Code.  Neovim, Zed, Emacs, and Sublime work too, and [other editors](docs/contributing/development-other-editors.md) covers pointing any Pyright- or venv-aware editor at the workspace.

**On Windows**, editing, lint, and unit tests run natively.  The MicroPython and CircuitPython desktop builds compile under WSL2 only, so the cross-runtime checks run there.  CI runs every check on a pull request either way.

## Setting up

First-time setup takes about five minutes once Python is installed.  Every step is safe to re-run.

**1. Fork and clone.**  Click **Fork** on the [ChuMicro repository](https://github.com/ChuMicro/ChuMicro), then:

```bash
git clone https://github.com/<your-username>/ChuMicro.git
cd ChuMicro
git remote add upstream https://github.com/ChuMicro/ChuMicro.git
```

Pushes go to your fork, `origin`, and updates come from the original repository, `upstream`.

**2. Bootstrap.**

```bash
python scripts/prepare_workspace.py
```

`prepare_workspace.py` reuses an active virtual environment or creates `.venv/`.  It installs every library and tool into it in editable mode, so your edits take effect without reinstalling.  It then generates IDE configs, and runs lint and the laptop unit tests to confirm the install.  It ends with a `Workspace is ready` banner.  It uses [`uv`](https://docs.astral.sh/uv/) when available and the standard library's `venv` otherwise.

**3. Activate the venv** in every new terminal:

```bash
source .venv/bin/activate        # Windows: .venv\Scripts\activate
```

Calling `.venv/bin/python` directly also works without activation.

**4. Run preflight.**

```bash
python scripts/run.py preflight
```

Preflight is the project's full check: lint, every library's unit tests on CPython, MicroPython, and CircuitPython, the docs build, the example and demo checks, and the size and version checks.  CI runs the same command on every pull request.  The first run also builds the MicroPython and CircuitPython desktop runtimes it tests against, which adds a few minutes.  Later runs reuse them and finish in a minute or two.  A last line starting `Preflight passed.` means the setup works, and a failure names its phase as [Reading a failure](#reading-a-failure) shows.

**5. Open your editor** at the project root.  PyCharm and VS Code pick up the committed configurations: see the [PyCharm notes](docs/contributing/development-pycharm.md) and [VS Code notes](docs/contributing/development-vscode.md).  Any other editor needs the venv's interpreter, and Pyright pointed at `pyrightconfig.json` in the root, as [other editors](docs/contributing/development-other-editors.md) shows.  Imports like `from chumicro_timing import ticks_ms` then resolve without red underlines.  When they show red, check that `which python` points into `.venv/`, run `python scripts/run.py sync-ide`, and reload the editor.

After a `git pull` that adds a library or changes dependencies, run `python scripts/run.py setup`.  It repeats the install and IDE refresh against the venv you already have.  It also works as the bootstrap inside your own environment, such as pyenv, conda, or an existing venv: activate that environment first.

## The development loop

1. **Edit** a library file.
2. **Run that library's tests** while you iterate.  `pytest libraries/timing/tests/` takes a few seconds, and IDE play buttons work.
3. **Run preflight before every commit**, docs-only commits included.  A docs change can still break the docs build or an example check.

A green preflight is the bar for opening a pull request.  The Python-version matrix and the `.mpy` install check run in CI only, and [Creating a Pull Request § CI checks](docs/contributing/pull-requests.md#ci-checks) shows how to reproduce each.  Any other CI failure after a green local preflight is a tooling bug: file it.

### Reading a failure

Preflight runs its phases in parallel and prints a `Phase summary:` table with `PASS` or `FAIL` beside each phase.  It ends with `Preflight failed at: <phase>`, just below the last lines of that phase's output.

- **`test` fails on coverage.**  The `Missing` column lists the lines no test runs.  Add tests for them.  Bare `pytest` skips the coverage gate, so a green `pytest` run can still fail here.  A line reachable only on a real board takes `# pragma: no cover`, as [Style Guide § Coverage exclusions](docs/contributing/style-guide.md#coverage-exclusions) explains.  When coverage fails on code outside your change, say so in the pull request, and a maintainer helps.
- **`lint` fails.**  Each message names the file, the line, and the change.  Lint runs ruff, then the project's own rules in `chumicro-checks`.  The naming rule's message spells out the exact rename.
- **`docs` fails with griffe warnings.**  A docstring or signature needs fixing, most often a missing type annotation or a malformed `Args:` section.  Types go on the signature, and the docstring carries descriptions.
- **`check-version` fails.**  A package's code changed and its `VERSION` did not.  [Releases and Promotion § When to bump VERSION](docs/contributing/releases.md#when-to-bump-version) says which changes need a bump and which bump.  `git diff --stat main` lists the files your branch changed.
- **`test-micropython` or `test-circuitpython` fails.**  The code passes on CPython and fails on a board runtime.  Reproduce it with `pytest libraries/<name>/tests --target unix-port --runtime micropython`, or `--runtime circuitpython`.  A `typing` import, a `from __future__` import, or a relative import in library code causes most of these, as [Style Guide § Type annotations](docs/contributing/style-guide.md#type-annotations) and [§ Imports](docs/contributing/style-guide.md#imports) explain.
- **`check-size` fails.**  The library's compiled size grew past its ceiling in `size-budgets.toml`.  Say so in the pull request.  A maintainer decides whether the growth earns a bigger budget.

## Your first change: a worked example

**Pick something small.**  A confusing docstring, a typo, or a one-line fix reviews faster and merges sooner than a large change.

**Branch off main:**

```bash
git checkout main
git pull upstream main
git checkout -b fix/clarify-rate-docstring
```

A branch name starts with `fix/`, `docs/`, or `feature/` to show its intent.  Every pull request targets `main`.

**Edit, then test the library you touched:**

```bash
pytest libraries/timing/tests/
```

The [cheat sheet](docs/contributing/cheat-sheet.md#testing) lists narrower runs: one file, a `-k` filter, or a stop on the first failure.

**Run preflight, then commit:**

```bash
python scripts/run.py preflight
git add libraries/timing/src/chumicro_timing/deadline.py
git commit
```

Git opens your editor for the message, which follows [Commit messages](#commit-messages):

```
Say that Rate fires when due() is called, not on a clock

The Rate docstring read as if Rate fired on its own timer.  It fires
only when due() runs and sees that a period has passed, so a main loop
that rarely calls due() sees late fires.  Users debugging "why didn't
my timer fire?" need to know that.
```

This change touches only a docstring, so its `VERSION` file stays as it is.

**Push and open the pull request:**

```bash
git push -u origin fix/clarify-rate-docstring
```

[Creating a Pull Request](docs/contributing/pull-requests.md#push-and-open-the-pull-request) takes it from there: the pull request form, CI, review, and keeping your fork in sync.

## Commit messages

A commit subject is one imperative line of about 70 characters at most.  The body explains why, since the diff already shows what.  When a decision record in `plans/decisions/` drove the change, the body names it.

A pull request lands on `main` as one squashed commit whose subject is the pull request's title, so the title follows the same rules.  Subjects on `main` read like these:

```
Credit Adafruit_CircuitPython_Ticks in the ticks module
Fix the artwork that 404s on every contributing page
Move the documentation to chumicro.com
```

- **Stage files by name**, never `git add -A` or `git add .`, so unrelated changes in your tree stay out of the commit.
- **Leave out `Co-Authored-By:` trailers**, AI-agent ones included.  Many agent tools add one to every commit, so delete it before committing.  The person running the work authors the commit.

## How changes land

Every change reaches `main` through a branch, a pull request, green checks, and a squash merge.  The branch ruleset blocks direct pushes to `main` for everyone, the maintainer included ([Decision 0120](plans/decisions/0120-main-is-pr-only.md)).  [Creating a Pull Request](docs/contributing/pull-requests.md) covers the required checks and the review.

## Testing

**1. Unit tests on your laptop.**  Each library's `tests/` folder runs under plain pytest in seconds, and most work needs only this layer.  A test builds the object under test with fakes plugged in for anything that needs hardware.  Libraries ship those fakes in a `testing` module, such as `from chumicro_timing.testing import FakeTicks`, so a test rarely needs a hand-written mock.

```bash
pytest libraries/timing/tests/
```

`python scripts/run.py test` runs the same tests with each library's coverage gate, one pytest process per library ([Decision 0009](plans/decisions/0009-per-library-test-runs.md)).  It covers the libraries your branch changed, or every package with `--all`.  Preflight runs it for you, so bare `pytest` suits iteration.

**2. The same tests on the board runtimes.**  MicroPython and CircuitPython each publish a desktop build, called a *unix port*, that runs on your laptop.  The whole unit suite runs under both, which catches code that works on CPython and breaks on a board, with no board attached:

```bash
pytest libraries/ --target unix-port --runtime both
```

Bare `pytest` needs the two binaries built once, with `python scripts/run.py prepare-micropython` and `python scripts/run.py prepare-circuitpython`, a few minutes each.  Preflight runs this layer too, and builds the binaries on first use.

**3. Functional tests on a real board.**  A *functional test* proves behavior a fake can't model: USB timing, filesystem semantics, radio state.  These tests live in `functional_tests/` folders and run *inside the board's Python*.  Pytest copies the test onto a connected board, runs it there, and reports back like any other test.

```bash
pytest libraries/timing/functional_tests/
```

These tests need a board registered with `python scripts/run.py add-device`.  Without one they skip, the expected result on a laptop with nothing plugged in.  [Device Testing](docs/contributing/device-testing.md) covers registration, multi-board runs, and the PR-summary output.  A functional test earns its place only where injected fakes can't prove the behavior.

**4. Examples on real hardware.**  Preflight checks that every example parses and that its imports resolve.  Deploying one with `chumicro-workspace deploy-example timing rate_blink`, and watching its output, checks by hand that the documented quick start still works.  Run it after changing an API an example uses.

## Writing an example

An example is the first ChuMicro code most people run, usually copied onto a board as `code.py`.  Its reader knows CircuitPython or MicroPython from Adafruit Learn guides or Arduino sketches, and has never seen this project.  [Style Guide § Examples and demos](docs/contributing/style-guide.md#examples-and-demos) holds the rules an example follows.

[`libraries/timing/examples/rate_blink.py`](libraries/timing/examples/rate_blink.py) is a complete small one.  Check yours with `python scripts/run.py verify-examples --libraries timing`, which checks syntax and imports.  Then run it on a board with `chumicro-workspace deploy-example timing rate_blink`.

Demos follow the same rules plus a few more, listed in [demos/README.md § Adding a demo](demos/README.md#adding-a-demo).

## Why the code looks the way it does

ChuMicro's code rules come from RAM measured in KB, three runtimes with different gaps, and debugging over a serial cable.  A decision record in [`plans/decisions/`](plans/decisions/) holds each rule's full reasoning.

**One shared loop runs everything.**  A long-running part of a program, such as the wifi connection or an MQTT client, is a *service* with two methods: `check(now_ms)` answers whether it has work, and `handle(now_ms)` does one piece of it.  The runner gives each service a turn on every pass of the loop.  A step-by-step flow is a generator, written with `yield from`, that the runner drives.  Every pause stays visible: readable in a serial traceback, and steppable in a debugger.  [Style Guide § Cooperative concurrency](docs/contributing/style-guide.md#cooperative-concurrency) explains why library code bans `async` and `await` ([Decision 0014](plans/decisions/0014-runner-pattern.md), [Decision 0087](plans/decisions/0087-generators-for-sequential-io.md)).

**A library takes its hardware through the constructor.**  A socket, an I2C bus, or a clock arrives as a constructor argument, with a default that loads only when needed.  Library code never imports `board`, `busio`, or a socket module at the top level.  Laptop tests then plug in fakes and run in milliseconds ([Decision 0010](plans/decisions/0010-library-testability.md)).

**Names spell words out.**  The linter flags single letters and a short list of abbreviations, and its message names the exact rename.  [Style Guide § Naming](docs/contributing/style-guide.md#naming) lists the rule and the reason the project keeps it.

**Memory tricks wait for a measurement.**  Write the clear version first.  [Style Guide § Memory patterns](docs/contributing/style-guide.md#memory-patterns-library-code-only) holds pre-allocated buffers, `memoryview`, and `const()` for when a measurement calls for them.

## When you're stuck

- **CI fails after local tests pass.**  Run the full preflight, since a local `pytest` run covers one library.  A MicroPython or CircuitPython failure reproduces as [Reading a failure](#reading-a-failure) shows.  `git status` shows a file left out of the commit.
- **`prepare_workspace.py` fails on a fresh clone.**  Check that `python --version` reports 3.11 or newer, and delete any half-built `.venv/` from an aborted run before retrying.

When nothing matches, open a [Discussion](https://github.com/ChuMicro/ChuMicro/discussions) for a question, a [bug report](https://github.com/ChuMicro/ChuMicro/issues/new?template=bug_report.yml) for something broken, or a [feature request](https://github.com/ChuMicro/ChuMicro/issues/new?template=feature_request.yml) for an idea.  Ask early.

## Going deeper

- **[`plans/decisions/`](plans/decisions/)** holds a record of every structural decision: what was decided and why.  Search it before proposing a structural change, because your idea may have a history.
- **To propose a design change**, open a [Discussion](https://github.com/ChuMicro/ChuMicro/discussions) that describes the problem and the tradeoff you see, and links any decision records it touches.  If the idea holds up, a maintainer works with you to land it as a new numbered record in `plans/decisions/` alongside the code change.
- **[`AGENTS.md`](AGENTS.md)** is the AI-agent operating manual.  It states the repository's rules in their strictest form, so it doubles as a reference for humans.
- **The [workbench template](https://github.com/ChuMicro/ChuMicro-Workbench-Template)** is the starter repository for a workspace, the folder that holds projects built *on* ChuMicro.  It shows how a downstream user assembles the libraries into an application.

## Code of conduct

This project follows the [Contributor Covenant](CODE_OF_CONDUCT.md).  Be decent to each other.

## License

By contributing, you agree your contributions will be licensed under the [MIT License](LICENSE).
