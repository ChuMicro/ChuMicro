# Contributing to ChuMicro

<img src="support/docs/chumicro_tip.png" align="left" width="64" style="margin-right: 16px; margin-bottom: 8px;">

Thanks for your interest in ChuMicro, a family of Python libraries that run unmodified on CircuitPython, MicroPython, and CPython.

There are several ways to be part of this project, and writing code is only one of them.  Using the libraries and telling us what happened is a contribution.  So is reporting a confusing error message, asking a question that exposes a documentation gap, or running an example on a board we haven't seen.  If you do want to change code, this page walks the whole path, and the tooling carries most of the weight: one command sets up your environment, one command runs every check CI will run.

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
| Understand the test layers | [Testing](#testing) below |
| Run tests on a real board | [Device Testing](docs/contributing/device-testing.md) |
| Understand `devices.yml` / `workspace.yml` / `secrets.toml` | [Workspace, devices, and secrets](docs/contributing/config-files.md) |
| Learn the code style | [Style Guide](docs/contributing/style-guide.md) |
| Open a pull request | [Creating a Pull Request](docs/contributing/pull-requests.md) |
| Add a new library | [Adding a New Library](docs/contributing/new-library.md) |
| Adopt one library into an existing codebase | [Standalone integration](docs/contributing/standalone-integration.md), then [Slimming your deploy](docs/contributing/slimming-your-deploy.md) |
| Add a host-only tool | [Adding a Workbench Package](docs/contributing/workbench.md) |
| Understand releases | [Releases and Promotion](docs/contributing/releases.md) |
| Work with an AI coding agent | [Working with Agents](docs/contributing/working-with-agents.md), plus the [agent style guide](docs/contributing/agent-style-guide.md) for prose tone |
| Recover from a broken state | [Troubleshooting](docs/troubleshooting/) |

Each page stands on its own.  Read the ones that match what you're doing and skip the rest.

## What you're contributing to

Each library lives in its own folder under `libraries/`, with its source, tests, examples, and docs together.  Host-side tools (deploy, REPL, test plugins) live under `workbench/` and run only on laptops.  A few things about the project's shape are worth knowing before you edit:

- **Code lands on three runtimes.**  Library code runs on devices that may have 256 KB of RAM and no `typing` module.  You don't set up the cross-runtime builds yourself; the tooling tests every library on all three runtimes automatically.  It does explain some style rules you'll meet below.
- **Nothing blocks.**  Libraries do their work in small steps inside a cooperative loop.  No `async`/`await`, no threads.  [Why the code looks the way it does](#why-the-code-looks-the-way-it-does) below has the reasoning.
- **Most changes touch one library.**  Features that span libraries land easier as a sequence of per-library PRs than as one large change.
- **Real hardware is optional.**  Fixing a bug, adding tests, or improving docs needs no microcontroller.  A board only enters the picture for on-device functional tests and for physically trying examples.

## Good first contributions

Real ways in that don't require knowing the codebase deeply:

- **Fix a typo or clarify a sentence** in any README, guide, or docstring.  For these you can skip local setup entirely: edit the file in GitHub's web UI (the pencil icon) and it forks and opens the PR for you.
- **Add an example script** to a library's `examples/` folder.  Pick something the library's guide explains but doesn't demonstrate.  Examples import only the library they demonstrate; `python scripts/run.py verify-examples` checks yours.
- **Improve test coverage.**  Run one library's tests, look at the uncovered lines, write tests for them.
- **Run a library on your board and say what happened.**  Even "worked on my ESP32-S3" is valuable.  Use the [board test report](https://github.com/ChuMicro/ChuMicro/issues/new?template=board_test_report.yml) template.

Browse [open issues](https://github.com/ChuMicro/ChuMicro/issues) and [discussions](https://github.com/ChuMicro/ChuMicro/discussions) for what people are working on; smaller items make easier first PRs.

## Prerequisites

- **Python 3.11 or newer.**  The host-side tooling needs it.  macOS: `brew install python`; Linux: your system package; Windows: [python.org](https://python.org).
- **Git**, any recent version.  Nothing beyond clone / branch / commit / push is required.
- **Any editor.**  The project ships ready-made configurations for PyCharm and VS Code, but nothing depends on them.  Neovim, Zed, Emacs, and Sublime all work; [other editors](docs/contributing/development-other-editors.md) covers pointing any Pyright- or venv-aware editor at the workspace.

**Windows users:** edit, lint, and run unit tests natively; use WSL2 for the cross-runtime checks (the MicroPython and CircuitPython desktop builds compile under WSL2, not native Windows).  CI runs everything either way, so you can also lean on it.

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

This creates a `.venv/`, installs every library and tool into it in editable mode, generates IDE configs, and runs a quick lint + test pass to confirm the install worked.  It uses [`uv`](https://docs.astral.sh/uv/) when available (faster), the stdlib `venv` otherwise.  Prefer your own environment (pyenv, conda, an existing venv)?  Activate it and run `python scripts/run.py setup` instead.

**3. Activate the venv** in every new terminal:

```bash
source .venv/bin/activate
```

(Or skip activation and call `.venv/bin/python` / `.venv/bin/chumicro-deploy` directly.)

**4. Verify.**

```bash
python scripts/run.py preflight
```

The first run also builds the MicroPython and CircuitPython desktop runtimes it tests against, which adds a few minutes; later runs reuse them and finish in a minute or two.  When it prints `Preflight passed.  Required CI checks should pass.`, you're set.  If it fails, the output names the failing step.

**5. Open your editor** at the project root.  PyCharm and VS Code pick up committed configurations ([PyCharm notes](docs/contributing/development-pycharm.md), [VS Code notes](docs/contributing/development-vscode.md)).  For anything else, [other editors](docs/contributing/development-other-editors.md) covers the two things that matter: use the venv's interpreter, and Pyright reads `pyrightconfig.json` from the root.  Either way, imports like `from chumicro_timing import ticks_ms` should resolve without red underlines.  If they don't, run `python scripts/run.py sync-ide` and reload the editor.

## The development loop

Day to day, the loop is short:

1. **Edit** a library file.  Installs are editable, so changes take effect immediately.
2. **Run that library's tests** while you iterate.  `pytest libraries/timing/tests/` takes a few seconds, and IDE play buttons work.
3. **Run preflight before committing.**

Preflight is the contract with CI:

```bash
python scripts/run.py preflight
```

One command, everything CI checks: lint, every library's unit tests with coverage gates, the same tests under the MicroPython and CircuitPython desktop builds, docs build, example imports, API and version checks, per-library size budgets.  CI runs the same command on every push, so a passing preflight is the bar for opening a PR.  (On native Windows, where the cross-runtime layer needs WSL2, run what you can locally and let CI cover that layer.)  If CI ever catches something preflight didn't, that's a tooling bug worth filing, not something you were supposed to foresee.

It takes a minute or two, so it isn't meant for every edit.  Use focused pytest runs while iterating and save preflight for the commit.

**Reading a failure.**  Preflight prints `FAIL` with the failing step.  The common ones:

- **Coverage not reached.**  Your change added lines the tests don't exercise; the `Missing` column lists them.  Lines only reachable on a real device can be marked `# pragma: no cover` ([Style Guide § Coverage exclusions](docs/contributing/style-guide.md#coverage-exclusions)).  If coverage fails on code you didn't touch, note it in the PR and a maintainer will help.
- **`ruff check` errors.**  Style violation; the message says what to change and where.
- **`griffe warnings`.**  A docstring problem, usually a missing type annotation or a malformed `Args:` section.
- **`check-version`.**  You changed a library's source without bumping its `VERSION` file (see [VERSION bumps](#version-bumps-and-publishing)).  Test-only, docs-only, and infrastructure changes don't need bumps.
- **A cross-runtime test failure.**  Passes on CPython, fails on a device runtime.  Reproduce with `pytest libraries/<name>/tests --target unix-port --runtime <micropython|circuitpython>`.  Usual culprits: `typing` or `__future__` imports (absent on devices) and relative imports in library code.

Docs-only changes can skip local preflight; CI still runs its full suite either way.  When unsure, run it.

## Your first change: a worked example

An end-to-end walkthrough with a docstring clarification as the example task.  Substitute your own change; the steps are identical.

**Pick something small.**  A confusing docstring, a typo, a one-line fix.  Small PRs review faster and merge sooner.

**Branch off main:**

```bash
git checkout main
git pull upstream main
git checkout -b fix/clarify-rate-docstring
```

Prefix branches with `fix/`, `docs/`, or `feature/` to signal intent.  Everything targets `main`.

**Edit, then test the library you touched:**

```bash
pytest libraries/timing/tests/
```

The [cheat sheet](docs/contributing/cheat-sheet.md) has the focused variants (`-k` filters, stop on first failure, one file or function) for tighter loops.

**Run preflight, then commit:**

```bash
python scripts/run.py preflight
git add libraries/timing/src/chumicro_timing/deadline.py
git commit
```

Write the message with an imperative subject and a body that explains *why*.  The diff already shows *what*:

```
timing: clarify Rate docstring around tick-based firing

The original phrasing implied Rate fires on a real clock; it actually
fires when due() observes that enough ticks have passed.  This matters
for users debugging "why didn't my timer fire?" when their main loop
is too busy to call due() often enough.

Affects: timing
```

**Push and open the PR:**

```bash
git push -u origin fix/clarify-rate-docstring
```

Click the "Compare & pull request" banner GitHub offers, check that the base is **ChuMicro/ChuMicro** `main` (not your own fork), and fill in the PR template.

**Then it's CI and review.**  CI runs on the PR automatically.  If something fails, fix locally and push to the same branch; it re-runs.  A maintainer reviews, maybe asks for changes; push fixes to the same branch and the PR updates.  Review comments after a green preflight aren't a failure on your part.  Automation checks that the code is sound; review checks what automation can't, like naming, scope, and API shape.

After the merge, your change is on `main`.  If you bumped a `VERSION` file, an experimental release publishes automatically ([Releases and Promotion](docs/contributing/releases.md)); otherwise your change rides along with the library's next release.

**Keeping your fork in sync** for the next change:

```bash
git checkout main
git pull upstream main
git push origin main
```

If `main` moves while your PR is open and you need its commits, rebase (`git rebase main`, then `git push --force-with-lease`).  This project keeps history linear, so rebases are preferred over merge commits.

## Testing

ChuMicro tests at four layers.  Each catches a different kind of bug, and together they make it hard for a regression to reach a user.  You'll mostly interact with the first one.

**1. Unit tests on your laptop.**  Each library's `tests/` folder, plain pytest, seconds to run.  Tests construct the object under test with fakes injected for anything hardware-shaped.  Libraries with hardware-shaped dependencies ship their fakes in a `testing` module (`from chumicro_timing.testing import FakeTicks`); pure-data libraries borrow their transport's fakes.  Either way, you rarely write a mock by hand.

```bash
pytest libraries/timing/tests/               # one library
pytest libraries/                            # everything
pytest libraries/ -k test_name_filter        # filter
```

For the commit-gating form with per-library coverage enforcement, `python scripts/run.py test` wraps the same tests (scoped to changed libraries by default, `--all` for a full sweep).  Bare pytest for iteration; the wrapper, or preflight, which includes it, before committing.

**2. The same tests on the device runtimes.**  MicroPython and CircuitPython publish desktop builds ("unix ports"), and the whole unit suite runs under them.  That's what catches "works on CPython, breaks on the board" without a board:

```bash
pytest libraries/ --target unix-port --runtime both
```

The first run needs the binaries built once: `python scripts/run.py prepare-micropython` and `prepare-circuitpython` (a few minutes each on a cold cache, reused after that).  CI runs this sweep on every push, so skipping it locally just moves the feedback later.

**3. Functional tests on a real board.**  For behavior a fake can't model: USB timing, filesystem semantics, radio state.  These live in `functional_tests/` folders and run *inside the device's Python*.  Pytest stages the test onto a connected board, executes it there, and reports back like any other test.

```bash
pytest libraries/timing/functional_tests/
```

You need a registered board (`python scripts/run.py add-device`); without one these tests skip cleanly, which is the expected no-hardware behavior, not an error.  Setup, multi-board runs, and the PR-summary output live in [Device Testing](docs/contributing/device-testing.md).  Most contributions never need a new functional test.  Write one only when the behavior can't be proven with injected fakes.

**4. Examples on real hardware.**  Preflight verifies every example still imports; actually deploying one (`chumicro-workspace deploy-example timing heartbeat_blink`) is the manual smoke test for "the documented quickstart still works."  Reach for it on API changes; release prep covers it systematically.

## Commit messages

Imperative subject that fits on one line (aim for 70 characters), prefixed with the area it touches; body explains why.  An `Affects: <library>` line at the bottom helps when the subject prefix doesn't already name the touched libraries; the examples below don't need one.  Two examples in the house style:

```
http_server: declare chumicro-config dep (audit fix #11)

Library lazy-imports MissingConfigKey from chumicro_config but the
pyproject didn't declare it as a dep. Users without chumicro-config
installed got an ImportError instead of the validation error.
```

```
dep-graph: hard-code a light background so the SVGs read on dark themes

The SVG was rendered without a background, so on a dark-theme GitHub
page the row labels, legend text, and edge arrows (all dark colors)
sat invisibly on the dark page background.
```

Two house rules: no `Co-Authored-By:` trailers (including AI-agent ones; commits are authored by the human running the work), and stage files explicitly rather than `git add -A` when you have unrelated changes lying around.  Full conventions: [Creating a Pull Request](docs/contributing/pull-requests.md).

## VERSION bumps and publishing

Libraries follow [semantic versioning](https://semver.org/), each with its own `VERSION` file.  If your PR changes a library's source (not just its tests or docs), bump it: patch for a fix, minor for a compatible feature, major for a breaking change.  CI's `check-version` reminds you if you forget.

On merge, a bumped library publishes automatically as an **experimental release**.  Promotion to the stable channel is a separate, deliberate maintainer step.  See [Releases and Promotion](docs/contributing/releases.md).

## Adding a new package

```bash
python scripts/run.py new-library my-sensor              # a device library
python scripts/run.py new-library --workbench my-tool    # a host-only tool
```

Both scaffold a working starter (tests pass, lint is clean, the example runs) that you replace with your implementation.  Before scaffolding, skim [Adding a New Library § Before you start](docs/contributing/new-library.md#before-you-start): a two-minute check that your idea isn't already in flight, already decided against, or better shaped as part of an existing library.

## Why the code looks the way it does

Some rules here differ from general-Python instinct.  Each exists because of a real constraint (RAM measured in KB, three runtimes with different gaps, debugging over a serial cable), and each has a decision record in [`plans/decisions/`](plans/decisions/) with the full reasoning.  The short versions:

**A cooperative loop instead of `async`/`await`.**  Services expose `check(now_ms)` ("do I have work?") and `handle(now_ms)` ("do one piece of it"), and the runner gives each a turn per tick.  Naturally sequential flows are written as generators (`yield from`) that the runner drives.  Both shapes keep every pause visible: readable in a serial traceback, steppable in a debugger.  `async` machinery differs per runtime and is incomplete on CircuitPython.  The `async` and `await` keywords, and asyncio itself, are banned in library code; a lint rule enforces it.  ([Decision 0014](plans/decisions/0014-runner-pattern.md), [Decision 0087](plans/decisions/0087-generators-for-sequential-io.md))

**Dependencies come in through the constructor.**  Libraries never import `board`, `busio`, or a socket module at the top level; hardware-shaped dependencies (a socket, an I2C bus, a tick source) arrive as constructor arguments with lazy defaults.  That's what makes the laptop test story real: tests inject fakes and run in milliseconds.  ([Decision 0010](plans/decisions/0010-library-testability.md))

**Descriptive names, even for short-lived variables.**  A bare `result = t.get(k)` three screens from where `t` was bound makes the next reader reconstruct context the name could have carried.  The linter flags single letters and a short list of banned abbreviations, and its message names the exact rename, so each hit is mechanical.  If you've written Python for years this rule will fight your habits; [Decision 0022](plans/decisions/0022-naming-conventions.md) owns that cost and explains why the project pays it.

**Memory patterns are applied when measured, not preemptively.**  Pre-allocated buffers and `memoryview` windows matter on a small heap, but they obscure simple code.  Write the clear version first; the [Style Guide § Memory patterns](docs/contributing/style-guide.md#memory-patterns-library-code-only) has the cookbook for when a measurement says it's time.

## When you're stuck

Most stuck moments resolve at one of these:

- **Imports show unresolved in the editor.**  Confirm the venv is active (`which python` points into `.venv/`), run `python scripts/run.py sync-ide`, reload the editor window.
- **Tests pass locally, fail in CI.**  Run full preflight (your local run may have been scoped to one library).  If the failure is under MicroPython or CircuitPython, reproduce with `--target unix-port --runtime <X>`.  Check `git status` for a file you forgot to commit.
- **`prepare_workspace.py` fails on a fresh clone.**  Check `python --version` is 3.11+, and delete any half-built `.venv/` from an aborted run before retrying.

When nothing matches: open a [Discussion](https://github.com/ChuMicro/ChuMicro/discussions) for questions, a [bug report](https://github.com/ChuMicro/ChuMicro/issues/new?template=bug_report.yml) for something broken, or a [feature request](https://github.com/ChuMicro/ChuMicro/issues/new?template=feature_request.yml) for an idea.  Better to answer a question than have you spin for an hour.

## Common mistakes

| Symptom | What's going on | Fix |
|---|---|---|
| `pytest` passes but preflight fails coverage | Bare pytest doesn't enforce the per-library coverage gate | Preflight's output lists the uncovered lines; add tests for them |
| `functional_tests/` says no device configured | No `devices.yml` yet | `python scripts/run.py add-device`; see [Device Testing](docs/contributing/device-testing.md) |
| `check-version` fails but you only changed tests | It only watches `src/` | No bump needed for test-only, docs-only, or infrastructure changes |
| `griffe warnings` in the docs build | Missing type annotation on a signature | Annotate the signature; the docstring carries descriptions |
| Editor shows red import underlines | Stale IDE config | `python scripts/run.py sync-ide`, reload the editor |
| Merge conflicts after pushing | `main` moved under you | Rebase onto the latest `main` |

## Going deeper

Once the basic loop feels comfortable:

- **[`plans/decisions/`](plans/decisions/)**: every structural decision has a record of what was decided and why.  Search here before proposing a structural change; your idea may have a history.
- **Proposing a design change:** open a [Discussion](https://github.com/ChuMicro/ChuMicro/discussions) describing the problem and the tradeoff you see, and reference any decision records it touches.  If it holds up, a maintainer works with you to land it as a new numbered record in `plans/decisions/` alongside the code change.
- **[`AGENTS.md`](AGENTS.md)**: the AI-agent operating manual, and a useful strict-rules reference for humans.
- **[Workspace template](https://github.com/ChuMicro/ChuMicro-Workspace-Template)**: the starter repo for projects built *on* ChuMicro.  Reading it shows how a downstream user assembles the libraries into an application.

## License

By contributing, you agree your contributions will be licensed under the [MIT License](LICENSE).
