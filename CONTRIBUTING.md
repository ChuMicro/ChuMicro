# Contributing to ChuMicro

<img src="support/docs/chumicro_tip.png" align="left" width="64" style="margin-right: 16px; margin-bottom: 8px;">

Welcome.  ChuMicro is an open platform for cross-runtime Python libraries targeting CircuitPython, MicroPython, and CPython.  Whether you're fixing a typo, adding tests, or publishing your own library — you belong here.

**You don't need to be an expert.**  The tooling handles most of the hard parts (coverage, linting, cross-runtime checks, release automation).  If you can run a few commands and follow the guidelines, you can contribute.

<br clear="left">

> ⚡ **Short on time?** The **[Contributor Cheat Sheet](docs/contributing/cheat-sheet.md)** is one page with everything you need — setup, workflow, and the only command you have to remember.

## What you're contributing to

ChuMicro is a family of small Python libraries for microcontroller projects — WiFi, MQTT, HTTP client and server, sockets, NTP, websockets, timing helpers, levelled logging, persistent storage, and more.  Each library installs independently and runs unmodified on CircuitPython, MicroPython, and CPython.  Instead of `async` / `await`, every networked service follows a tick-based cooperative-loop pattern that's transparent to debug on a serial console.

A few things this shape means for contributing:

- **Cross-runtime by default.**  Library code lands on devices that may have 256 KB of RAM and no `typing` module.  The tooling tests every library under all three runtimes automatically; you don't set up the cross-runtime builds yourself.
- **Tests next to the code.**  Each library has its own `tests/` directory with CPython unit tests, and optionally a `functional_tests/` directory for tests that stage onto a real connected board.
- **Preflight mirrors CI.**  `python scripts/run.py preflight` is one command that runs every CI check locally before you commit.
- **Lots of small libraries, not one big one.**  Most contributions touch a single library.  Bigger features that span libraries are easier to land as a sequence of per-library PRs than as one large change.

The rest of this page walks through what that looks like in practice.

## Good first contributions

Not sure where to start?  These are real ways to contribute that don't require deep knowledge of the codebase:

- **Fix a typo or clarify a sentence** in any README, guide, or docstring — docs-only PRs skip most CI checks.
- **Add an example script** to a library's `examples/` folder — pick a use case the library's guide explains but doesn't demo.
- **Improve test coverage** — run `python scripts/run.py test --libraries <name>`, check the `Missing` column, and write tests for uncovered lines.
- **Try a library on your board** and report what happened — even "it worked on my ESP32-S3" is valuable.  Use the [board test report](https://github.com/ChuMicro/ChuMicro/issues/new?template=board_test_report.yml) template.

Browse [open issues](https://github.com/ChuMicro/ChuMicro/issues) and [discussions](https://github.com/ChuMicro/ChuMicro/discussions) for things people are working on or thinking about; smaller items are easier first PRs.

## Reading guide

| What you want to do | Read this |
|---|---|
| **Get the short version** | [Contributor Cheat Sheet](docs/contributing/cheat-sheet.md) — one page, everything you need |
| **Find something to work on** | [Good first contributions](#good-first-contributions) |
| **Set up your environment** | [Setting up your development environment](#setting-up-your-development-environment) below |
| **Understand the development loop** | [How development works here](#how-development-works-here) below |
| **Walk through your first PR end-to-end** | [Your first change: a worked example](#your-first-change-a-worked-example) below |
| **Understand the four test layers** | [Testing](#testing) below |
| **Configure real-board testing** | [Device Testing](docs/contributing/device-testing.md) |
| **Understand devices.yml / workspace.yml / secrets.toml** | [Workspace, devices, and secrets](docs/contributing/config-files.md) |
| **Understand the code style** | [Style Guide](docs/contributing/style-guide.md) |
| **Open a pull request** | [Creating a Pull Request](docs/contributing/pull-requests.md) |
| **Add a new library** | [Adding a New Library](docs/contributing/new-library.md) |
| **Add a host-only workbench tool** | [Adding a Workbench Package](docs/contributing/workbench.md) |
| **Understand releases** | [Releases and Promotion](docs/contributing/releases.md) |
| **Use an AI coding agent** | [Working with Agents](docs/contributing/working-with-agents.md) |
| **Get unstuck** | [When you're stuck](#when-youre-stuck) below |
| **Recover from a broken state** | [Troubleshooting](docs/troubleshooting/) — macOS CIRCUITPY wedge, stale mounts |

Each page is self-contained.  You don't need to read all of them — just the ones relevant to what you're doing.

## Prerequisites

| Tool | Version | Why |
|------|---------|-----|
| Python | ≥ 3.11 | The host-side tooling uses modern Python features.  macOS: `brew install python`; Linux: system package; Windows: [python.org](https://python.org). |
| Git | any recent | Standard version control.  The project uses linear history on `main` — no required Git features beyond clone / branch / commit / push. |
| IDE (optional) | Any editor with a terminal | PyCharm, VS Code, Neovim, Zed, Emacs, Sublime — all work.  Pick what you're already comfortable with.  The project ships configurations for PyCharm and VS Code but nothing requires them. |

**Windows users:** use native Windows for editing, linting, and unit tests.  Use WSL2 for unix-port cross-runtime checks — the MicroPython and CircuitPython unix ports build under WSL2 but not under native Windows.

**Real hardware is optional.**  Fixing a bug, adding tests, improving docs — none of these require a microcontroller.  Hardware is only needed for `functional_tests/` runs and for trying examples physically on a board.

## Setting up your development environment

A first-time setup takes about 5 minutes once Python is installed.  Four commands do everything; the bootstrap is safe to re-run if something goes wrong.

### 1. Fork and clone

Click **Fork** at the top right of the [ChuMicro repository on GitHub](https://github.com/ChuMicro/ChuMicro).  This creates a copy under your own account that you can push to without needing write access to the original.

Then clone your fork locally and add the original as a remote so you can pull updates:

```bash
git clone https://github.com/<your-username>/ChuMicro.git
cd ChuMicro
git remote add upstream https://github.com/ChuMicro/ChuMicro.git
```

After this you have two remotes — `origin` pointing at your fork (where you push) and `upstream` pointing at the original repository (where you pull updates from).

### 2. Bootstrap the workspace

```bash
python scripts/prepare_workspace.py
```

This is the first-time bootstrap.  It auto-detects or creates a `.venv/` directory at the repo root, installs every library and workbench tool in editable mode (`pip install -e`), regenerates IDE configs, and runs lint + host tests to confirm the install worked.  Expect one to two minutes on the first run; subsequent runs are faster because pip caches the wheels.

`prepare_workspace.py` uses [`uv`](https://docs.astral.sh/uv/) if it finds it on your PATH (much faster install), otherwise it falls back to the stdlib `venv` module.  Either path produces the same result.

**After this first run:** use `python scripts/run.py setup` for everyday refreshes (pulling new libraries, updating deps, re-syncing IDE configs).  `prepare_workspace.py` is the bootstrap; `run.py setup` is the day-to-day refresh.

### 3. Activate the venv

```bash
source .venv/bin/activate
```

Activate the venv every time you open a new terminal in this project.  All the project commands (`python scripts/run.py …`, `chumicro-deploy …`, `chumicro-workspace …`) assume the venv is active.

If you'd rather not activate, you can invoke `.venv/bin/python scripts/run.py …` and `.venv/bin/chumicro-deploy …` directly — same result.

### 4. Verify the install

```bash
python scripts/run.py preflight
```

Expect about one minute the first time.  When it finishes, look for:

```
Preflight passed — required CI checks should pass.
```

If it fails, the output tells you which step failed and where — fix it and re-run.  Preflight is explained in detail in [the next section](#how-development-works-here).

### 5. Open in your editor

Point your editor at the project root.  IDE-specific notes:

- **PyCharm** — open the directory; pick the `.venv` interpreter when prompted.  Committed run configurations under `.idea/runConfigurations/` and source-root settings work without extra setup.  See [PyCharm setup](docs/contributing/development-pycharm.md).
- **VS Code** — `code .` from the project root.  Install the recommended extensions when prompted.  See [VS Code setup](docs/contributing/development-vscode.md).
- **Other editors** — Pyright reads `pyrightconfig.json` from the project root; activate the venv before launching the editor.  See [other editors](docs/contributing/development-other-editors.md).

You should not see red underlines on imports like `from chumicro_timing import ticks_ms` once setup is complete.  If you do, run `python scripts/run.py sync-ide` and reload your editor.

## How development works here

ChuMicro's contribution workflow is unusually script-driven for a Python project, because the code targets three runtimes and runs on microcontrollers.  Understanding the loop pays off quickly.

### The development loop

A typical edit-test cycle:

1. **Edit** a library file.  IDE imports resolve through the editable installs that `prepare_workspace.py` set up — `from chumicro_timing import ticks_ms` works in any editor that uses the venv's interpreter.
2. **Run focused tests** while iterating.  `pytest libraries/timing/tests/` is the everyday command — fast (a few seconds), picks up changes immediately because the install is editable, works in IDE play buttons.
3. **Run preflight** before committing.  Details below.

The first two steps stay tight (seconds).  Preflight takes around a minute and isn't meant for every edit; run it before commit.

### Preflight: the contract with CI

Preflight is one command that runs every CI check locally:

```bash
python scripts/run.py preflight
```

Specifically, preflight runs:

- **Lint** — Ruff plus the workspace's `CHU0NN` rules (descriptive names, whitespace, no mono-repo references leaking into publishable trees).
- **Tests** — every library's CPython unit tests, with the per-library coverage gate.
- **Cross-runtime tests** — every library's tests under MicroPython and CircuitPython unix-port builds (catches "works on CPython, breaks on MicroPython" before code reaches a board).
- **Docs build** — mkdocs + griffe for every library; fails on missing docstrings or wrong section format.
- **Example imports** — every example file under `libraries/*/examples/` must parse and import cleanly.
- **API + version checks** — flags removed public symbols without a `VERSION` bump.

CI runs the same `preflight` command on every push, plus a few extras that are expensive locally — building distribution wheels, validating the CircuitPython and MicroPython bundle packagings.  Anything CI catches that preflight wouldn't is a tooling gap, not a contributor responsibility — file it as a bug; the goal is preflight ↔ CI parity.

A passing preflight is the bar for opening a PR.

### Coverage gates

Every library has a per-library coverage gate (85% by default, configured in each library's `pyproject.toml`).  If your tests don't exercise enough lines, `run.py test` fails with the `Missing` column showing exactly which lines need coverage.

You don't need to opt in — `pytest` and preflight apply the gate automatically.  Agent-driven workflows run against a stricter version of the same gate, which the tooling switches to on its own.

The [cheat sheet](docs/contributing/cheat-sheet.md) has the command for browsing covered vs uncovered lines as an HTML report.

## Your first change: a worked example

Here's an end-to-end walkthrough of contributing a small change.  The example task is a docstring clarification; substitute your own task and the steps are identical.

### Pick something small

Pick a docstring you noticed could be clearer, a typo in a README, or a one-line fix from a recent commit you spotted.  Smaller is better for a first PR — easier to review, faster to merge, builds confidence for a larger one.

### Branch off main

```bash
git checkout main
git pull upstream main                              # pull the latest from the original repo
git checkout -b fix/clarify-heartbeat-docstring     # create your branch
```

Branch naming: prefix with `fix/`, `docs/`, or `feature/` to signal intent.  Everything targets `main`; there's no `develop` branch.

### Edit and test

Make the change.  Then run the test for the library you touched:

```bash
pytest libraries/timing/tests/
```

The [cheat sheet](docs/contributing/cheat-sheet.md) has the focused-test variants — `-k` filters, stop-on-first-failure, scoping to one file or function.  Reach for those during tight iteration loops.

### Run preflight before committing

```bash
python scripts/run.py preflight
```

Wait for `Preflight passed — required CI checks should pass.`  If anything fails, the output tells you what to fix.  Don't commit until preflight passes — pushing a broken commit means a round-trip through CI failure + a forced re-push.

### Commit

```bash
git add libraries/timing/src/chumicro_timing/heartbeat.py
git commit
```

Git opens your editor for the commit message.  Use an imperative subject line and explain *why* in the body:

```
Clarify Heartbeat docstring around tick-based timing

The original phrasing implied Heartbeat fires on a real clock; it
actually fires when poll() observes that enough ticks have passed.
This matters for users debugging "why didn't my heartbeat fire?"
when their main loop is too busy to call poll() often enough.

Affects: timing
```

Subject is imperative ("Clarify…", not "Clarified…" or "Clarifies…"), body explains *why* not *what* (the diff shows what), affected libraries are named at the bottom.

### Push and open the PR

```bash
git push -u origin fix/clarify-heartbeat-docstring
```

GitHub's response includes a "Compare & pull request" banner — click it.  GitHub auto-loads the PR template; fill in each section (Summary, Changes, How to verify, Device testing, Version impact, Breaking changes).

GitHub usually pre-selects the right base — verify the header reads **base repository: ChuMicro/ChuMicro** and **base: main**.  If it points at your own fork instead, change the base repository dropdown.

### Wait for CI, respond to review

CI runs automatically on your PR (about 1-2 minutes).  If something fails, click the failed check to see the log, fix locally, push to the same branch — CI re-runs automatically.

A maintainer reviews the PR.  They may approve and merge, request changes, or leave comments for discussion.  Respond to comments and push fixes to the same branch; the PR updates as you push.

### After merge

Your change is on `main`.  If you bumped a `VERSION` file, an experimental release publishes automatically — see [Releases and Promotion](docs/contributing/releases.md) for what that means.  If not, the change is just in the next experimental release of whatever library next gets a version bump.

You're done.  Next change is easier.

## Keeping your fork in sync

Before starting new work, pull the latest `main` from upstream (the original repository) so you start from current code:

```bash
git checkout main
git pull upstream main
git push origin main           # update your fork too, so the GitHub UI stays current
```

If `main` moves while your branch is open and you need the new commits in your branch, rebase:

```bash
git checkout my-branch
git rebase main                # replay your commits on top of the latest main
git push --force-with-lease    # update the PR (force is safe with --force-with-lease)
```

Rebasing keeps history linear and avoids merge commits cluttering the PR.  See [Git's rebase docs](https://git-scm.com/book/en/v2/Git-Branching-Rebasing) if you hit conflicts you're unsure how to resolve.

## Preflight in depth

`python scripts/run.py preflight` is the one command this guide asks you to memorise.  It runs the automated checks from the [Testing](#testing) section below — CPython unit tests, the same tests under MicroPython and CircuitPython unix-port builds, and example-import checks — plus lint, docs, and version gates.  On-device functional tests are opt-in (`--with-functional`).  A few things worth knowing about how preflight behaves:

### When to run it

- **Always before committing a non-trivial change.**  Preflight catches problems that don't surface in editor / IDE feedback — cross-runtime mismatches, coverage gaps, docstring issues.
- **Not between every edit.**  Use focused `test --libraries <name>` runs for iteration; save preflight for the contract-with-CI moment.
- **Before pushing if you rebased.**  Rebasing can re-introduce conflicts in test files; preflight catches them.

### Reading a failure

Preflight prints `FAIL` followed by the failing step.  Common patterns:

- **`Required test coverage of 85.0% not reached`** — your tests don't exercise enough lines.  Look at the `Missing` column to see which lines need coverage.  If the missing lines are runtime-only branches that can't be tested on CPython, mark them with `# pragma: no cover` — see [Style Guide § Coverage exclusions](docs/contributing/style-guide.md#coverage-exclusions).
- **`ruff check` errors** — code style violation.  Click the file:line in your terminal (if your terminal supports it) or open the file at that line; the error message tells you what's wrong.
- **`griffe warnings detected`** — docstring formatting issue.  Usually a missing type annotation on a function signature or a malformed `Args:` / `Returns:` section.
- **`check-version` failure** — you changed library source under `src/` but didn't bump the library's `VERSION` file.  Edit `libraries/<name>/VERSION` (patch bump is usually right) and re-run.
- **Cross-runtime test failure** — your test passes under CPython but fails under MicroPython or CircuitPython.  Reproduce locally with `python scripts/run.py test-micropython` or `test-circuitpython`.  Usual culprits: `typing` imports (not available on devices), `from __future__` imports (no `__future__` module on devices), relative imports in library code (break CircuitPython RAM-mode deploys).

### Coverage failure on code you didn't touch

If preflight fails coverage on code that's pre-existing, note it in the PR description.  A maintainer can help fill the gap or mark an exception.  Don't artificially bump coverage to pass — that's exactly what the gate is trying to catch.

### Skipping preflight for trivial fixes

Docs-only PRs and trivial typo fixes can skip the full preflight — CI handles them separately and most checks are skipped automatically for `*.md` changes.  Use judgment; if you're unsure, run it.

<details>
<summary>What every preflight step does in detail (click to expand)</summary>

- **Test coverage** per library (85% gate, line + branch).  Run individually: `python scripts/run.py test --libraries <name>`.
- **Scripts infrastructure tests:** `python scripts/run.py test-scripts`.
- **No lint errors:** `python scripts/run.py lint`.
- **Examples must parse:** `python scripts/run.py verify-examples --libraries <name>`.
- **Docs must build:** `python scripts/run.py docs --libraries <name>`.
- **No API breakage** without a VERSION bump (`check-api` and `check-version`).
- **Cross-runtime compatibility:** every library's tests run under MicroPython and CircuitPython unix ports.

</details>

## Testing

ChuMicro tests at four layers.  Each catches a different class of bug; together they make it hard for a regression to reach a user.  Preflight runs the automated layers (unit tests, cross-runtime unit tests, example-import checks) on every commit; the hardware-touching parts (on-device functional tests, manual example deploys) are opt-in.

### Unit tests (CPython)

The everyday layer.  Each library has a `tests/` directory next to its source, with pytest tests that exercise the code on CPython.  Fast — a full library's tests run in a second or two.

```bash
pytest libraries/timing/tests/
```

These tests catch logic bugs, regressions in covered code paths, and API behavior changes.  The shape: construct the object under test with fakes injected for any hardware-touching dependencies (sockets, ticks, I2C buses), then assert observable behavior.  Each library's `testing.py` ships fakes downstream tests can import (`from chumicro_timing.testing import FakeTicks`).

Add a unit test when you add code.  The per-library coverage gate fails preflight if you don't.

### Cross-runtime unit tests

The same unit tests, run under MicroPython and CircuitPython's "unix port" builds — desktop versions of the device runtimes that catch "works on CPython, breaks on the device" before code reaches a board.

```bash
python scripts/run.py test-all-runtimes
```

The first run builds the unix-port binaries under `.tools/` (gitignored, about a minute); subsequent runs reuse them.  CI runs the same sweep on every push, so contributors without unix-port builds locally still get the protection.

These tests catch the runtime-specific gotchas — `typing` imports that don't exist on devices, `from __future__` imports that fail there, relative imports that break CircuitPython RAM-mode deploys, library quirks in the device standard libraries.

Test files that need to skip on a particular runtime declare it via the `__chumicro_runtimes__` module marker — see the [Style Guide](docs/contributing/style-guide.md) for the format.

### On-device functional tests

For behavior that only emerges on real hardware — USB-CDC timing, filesystem semantics, GPIO state, anything a fake can't realistically model.  These tests live in `functional_tests/` (parallel to `tests/`) and run in the device's actual Python runtime.

How it works: the `chumicro-pytest-device` plugin intercepts pytest collection under `functional_tests/`, stages the test source and library source onto a connected board, runs the test inside the device runtime, and reports the result back through the host's pytest — same UX as any other pytest run.

```bash
pytest libraries/timing/functional_tests/
```

You need a board plugged in and registered (`python scripts/run.py add-device …`).  Without a `devices.yml`, the tests skip cleanly — no error, no false failure.  Full hardware setup (deploy modes, multi-runtime, wifi credentials, IDE play-button integration) lives in [Device Testing](docs/contributing/device-testing.md).

Write a functional test only when the behavior under test can't be proven with constructor injection + fakes.  Most contributions don't need new ones; reach for functional tests when you're touching `chumicro-deploy`, `chumicro-pytest-device`, the on-device transport paths, or any code where the bug only shows up on a real device.

### Example execution (manual testing)

Every library ships runnable examples in `libraries/<name>/examples/`.  Two pieces of testing cover them.

The automated piece — `verify-examples` — AST-parses every example file to confirm it imports cleanly with the library's declared deps.  This catches "the example references a function the library doesn't export" before a user does.  Preflight runs it on every commit.

The manual piece — deploying an example to a real board — is how to confirm the documented pattern still works on actual hardware:

```bash
chumicro-workspace deploy-example timing heartbeat_blink
```

This is the smoke-test that catches "unit tests pass but the documented quickstart no longer runs."  Not required on every PR — reach for it on API changes, significant refactors, or anything that affects user-visible behavior.  A release-prep pass typically includes deploying each touched library's examples to the project's board matrix.

## Commit messages

Imperative subject line under 70 characters; body explains *why* not *what* (the diff already shows what); name affected libraries.

Real examples from this repository's history:

```
docs: cold-reader audit of contributing surface

Sweep across CONTRIBUTING.md, every docs/contributing/*.md, and the
root README's "Running tests" section to align them on hero shape,
prune AI-tics, and surface capabilities that had drifted out of
human-facing docs.
```

```
dep-graph: hard-code a light background so the SVGs read on dark themes

The SVG was rendered without a background, so on a dark-theme GitHub
page the row labels, legend text, and edge arrows (all dark colors)
sat invisibly on the dark page background.  Only the node boxes,
which have their own light fill, stayed legible.
```

```
http_server: declare chumicro-config dep (audit fix #11)

Library lazy-imports MissingConfigKey from chumicro_config but the
pyproject didn't declare it as a dep — users without chumicro-config
installed got an ImportError instead of the validation error.
```

A few things to notice:

- Subject line names the area (`docs:`, `dep-graph:`, `http_server:`) — helps reviewers skim history.
- Subjects are short, no trailing period.
- Body explains the *reason* — what was wrong, why this fixes it.
- Multi-paragraph bodies are fine when the change has nuance.

A few conventions:

- Don't add `Co-Authored-By:` trailers, including AI-agent trailers.  Commits in this repo are authored by the human running the work.
- Stage specific files (`git add libraries/timing/...`) rather than `git add -A` when you have a mix of changes — keeps unrelated work out of the commit.

Full conventions and the multi-line-message technique live in [Creating a Pull Request](docs/contributing/pull-requests.md).

## VERSION bumps

Libraries use [semantic versioning](https://semver.org/).  If your PR changes library source code (not just tests, docs, or infrastructure), bump the `VERSION` file:

| Change type | Bump | Example |
|---|---|---|
| Bug fix, no API change | Patch | `0.1.15` → `0.1.16` |
| New feature, backward-compatible | Minor | `0.1.15` → `0.2.0` |
| Breaking API change | Major | `0.1.15` → `1.0.0` |

CI catches missed bumps automatically — `check-version` will let you know if you forgot.

## Publishing

When your PR merges to `main` with a VERSION bump, the library auto-publishes as an **experimental release** to PyPI, the experimental bundle, and experimental docs — no manual steps.

**Stable promotion** is a separate maintainer step.  Open a [Stable Promotion Request](https://github.com/ChuMicro/ChuMicro/issues/new?template=stable_promotion.yml) when an experimental release is ready.  See [Releases and Promotion](docs/contributing/releases.md) for the full pipeline.

## Adding a new package

For a device library (cross-runtime, ships to PyPI + CircuitPython bundle + MicroPython bundle):

```bash
python scripts/run.py new-library my-sensor
```

This scaffolds `libraries/my-sensor/` with a working starter — tests pass at 100% coverage, lint is clean, the example runs.  Replace the starter code with your implementation.  Full walkthrough: [Adding a New Library](docs/contributing/new-library.md).

For a host-only workbench tool (CPython only, ships to PyPI):

```bash
python -m chumicro_workspace new --workbench my-tool
```

The `scripts/run.py new-library` shim is library-only today; the workbench scaffolder is reachable through the underlying CLI.  Full walkthrough: [Adding a Workbench Package](docs/contributing/workbench.md).

Before scaffolding, skim [Adding a New Library § Before you start](docs/contributing/new-library.md#before-you-start) — a two-minute scope check whether your idea is already in flight, already decided against, or in the wrong category.

## Why the code looks the way it does

The non-obvious rules in this codebase come from real constraints — RAM budgets, runtime quirks, debuggability on a board where serial is your only window into what's happening.  Each rule has a decision record in [`plans/decisions/`](plans/decisions/) with the full reasoning; here's the short version of *why* each one exists.

### Tick-based runner instead of `async` / `await`

Why: every state change in a tick-based system is visible from a `print()` on a serial console.  Nothing hides inside an event loop.  When a service stops working on a deployed device, debug visibility matters more than syntactic concurrency.

How: services expose `check(now_ms) -> bool` to say "I have work to do this tick" and `handle(now_ms)` to do one chunk of work.  The runner gives each registered service a turn each pass through the main loop.  No async, no threads, no ISRs in user code.

Full reasoning: [Decision 0014](plans/decisions/0014-runner-pattern.md).

### Constructor injection for I/O and time

Why: libraries that import `board` or `busio` or `time` at the top level can't be tested without real hardware.  When the only test path involves a deployed board, the test loop slows from seconds to minutes — and most contributions don't have boards plugged in.

How: pass hardware-touching dependencies (I2C bus, socket, ticks function) as constructor parameters.  Real code injects the real thing; tests inject a fake from `chumicro_<name>/testing.py`.

Full reasoning: [Decision 0010](plans/decisions/0010-library-testability.md).

### Two ways to run tests, one for iteration and one for gating

Why: every library has its own coverage threshold (85% by default), and a single shared pytest session can't easily apply per-library thresholds.  Multiple libraries also have overlapping test-file names (`test_core.py` shows up in several libraries) that would collide in a single session.

How: bare `pytest` from the repo root is the day-to-day command — fast, picks up edits immediately, handles the file-name collisions via importlib mode, deselects `functional_tests/` automatically.  `python scripts/run.py test` wraps pytest in per-library subprocesses that enforce the coverage gates; preflight uses that wrapper.  Day-to-day iteration: bare pytest.  Pre-commit: preflight.

Full reasoning: [Decision 0009](plans/decisions/0009-per-library-test-runs.md).

### Descriptive names, even for short variables

Why: `for i in range(10)` is fine.  `result = e.code` is not — `e` could be exception, environment, edge, event.  The project optimizes for readability across experience levels — full words over abbreviations.  The linter handles this automatically; you don't memorize the list.

How: `CHU001` flags single-letter variables outside for-loop targets and a small banned-abbreviation list (`buf` → `buffer`, `cmd` → `command`, `exc` → `exception`).  The error message tells you exactly what to rename.

Full reasoning: [Decision 0022](plans/decisions/0022-naming-conventions.md).  Full style: [Style Guide](docs/contributing/style-guide.md).

### Memory patterns — optional on day one

Why: `const()`, `memoryview`, pre-allocated buffers all help on a 256-KB MCU but obscure simple code.  Apply them when measurements show they matter, not preemptively.

How: write correct code first.  When a library hits a memory ceiling on a real board, optimize.  The [Style Guide § Memory patterns](docs/contributing/style-guide.md#memory-patterns-library-code-only) section has the cookbook for when you get there.

## Common mistakes

| Symptom | Cause | Fix |
|---|---|---|
| Tests pass via `pytest` but `preflight` fails coverage | Bare `pytest` doesn't enforce the per-library coverage gate | Run `python scripts/run.py preflight` before committing — it surfaces the missing-coverage lines |
| `functional_tests/` says no device is configured | `devices.yml` is missing or has wrong board IDs | Run `python scripts/run.py setup`, then `add-device`.  See [Device Testing](docs/contributing/device-testing.md) |
| `check-version` fails but you only changed tests | CI checks source changes under `src/` | No VERSION bump needed for test-only / docs-only / infra changes — note in PR description |
| Coverage fails on code you didn't touch | Pre-existing gap | Note in PR description; a maintainer can help |
| `griffe warnings detected` in docs build | Missing type annotation | Add types to function signatures: `def foo(x: int)` — docstrings carry descriptions |
| Merge conflicts after pushing | `main` moved while you were working | Rebase your branch onto the latest `main` |
| PyCharm/VS Code shows red import underlines | IDE configs are stale | `python scripts/run.py sync-ide`, then reload the editor |

## When you're stuck

A short troubleshooting checklist before reaching for help — most stuck moments resolve at one of these steps.

### Imports show as unresolved in your editor

1. Confirm the venv is active: `which python` should point to `.venv/bin/python` under your project directory.
2. Run `python scripts/run.py sync-ide` — regenerates IDE configs from the current workspace layout.
3. Reload your editor's window.  In VS Code: Command Palette → Developer: Reload Window.  In PyCharm: right-click the project root → Reload from Disk.

### Tests pass locally but fail in CI

1. Was your local run on the changed package only?  Run `python scripts/run.py preflight` (full sweep) to reproduce.
2. Is the failure under MicroPython or CircuitPython?  Reproduce locally with `python scripts/run.py test-micropython` or `test-circuitpython`.
3. Did you forget to commit a file?  `git status` shows untracked files.

### `prepare_workspace.py` fails on a fresh clone

1. Check your Python version: `python --version` must be ≥ 3.11.
2. If you're on macOS and using the system Python, install a real Python via Homebrew or [python.org](https://python.org).
3. If a partial `.venv/` exists from an aborted run, delete it and try again — `prepare_workspace.py` rebuilds it.

### Preflight passes locally but a maintainer asks for changes

This isn't being stuck — it's the review process working.  A passing preflight means the code is technically sound; review covers things automation can't (API shape, naming, doc clarity, scope).  Respond to the comments and push fixes to the same branch.

### Nothing on this checklist matches

Ask.  Where:

- **Question?** Open a [Discussion](https://github.com/ChuMicro/ChuMicro/discussions).
- **Something broken?** File a [bug report](https://github.com/ChuMicro/ChuMicro/issues/new?template=bug_report.yml).
- **Have an idea?** File a [feature request](https://github.com/ChuMicro/ChuMicro/issues/new?template=feature_request.yml).
- **Want to try an AI agent on the work?** See [Working with Agents](docs/contributing/working-with-agents.md).

Asking is welcome.  Better to answer a question than have you spin for an hour.

## Going deeper

Once you're comfortable with the basic loop, these resources explain the *why* behind the project's shape:

- **[`plans/decisions/`](plans/decisions/)** — every structural / pattern / tooling decision has an ADR explaining what was decided, when, and why.  Search before proposing a structural change; the decision doc tells you if your idea was already considered.
- **[`plans/next-up.md`](plans/next-up.md)** — the agent-managed work queue.  Current focus + recent history.
- **[`plans/patterns.md`](plans/patterns.md)** — implementation patterns (recv-buffer reuse, lazy adapter selection, Runner-shaped services) with worked examples.
- **[`AGENTS.md`](AGENTS.md)** — the AI-agent operating manual.  Useful for humans too as a strict-rules reference.
- **[Workspace template](https://github.com/ChuMicro/ChuMicro-Workspace-Template)** — the clone-and-go starter repo for projects built *on* ChuMicro.  Reading it shows how a real downstream user assembles libraries into an application.

For per-topic sub-docs (style guide, device testing, releases, PR flow, new library, workbench, agents) see the [Reading guide](#reading-guide) table above.

## License

By contributing, you agree your contributions will be licensed under the [MIT License](LICENSE).
