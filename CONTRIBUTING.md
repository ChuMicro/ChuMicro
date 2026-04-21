# Contributing to ChuMicro

<img src="support/docs/chumicro_tip.png" align="left" width="64" style="margin-right: 16px; margin-bottom: 8px;">

Welcome! ChuMicro is an open platform for cross-runtime Python libraries targeting CircuitPython, MicroPython, and CPython. Whether you're fixing a typo, adding tests, or publishing your own library — you belong here.

**You don't need to be an expert.** The tooling handles most of the hard parts (coverage, linting, cross-runtime checks, release automation). If you can run a few commands and follow the guidelines, you can contribute.

<br clear="left">

> ⚡ **Short on time?** The **[Contributor Cheat Sheet](docs/contributing/cheat-sheet.md)** is one page with everything you need — setup, workflow, and the only command you have to remember.

## Good first contributions

Not sure where to start? These are real ways to contribute that don't require deep knowledge of the codebase:

- **Fix a typo or clarify a sentence** in any README, guide, or docstring — docs-only PRs skip most CI checks.

  > *Example:* A docstring says "returns a list" but the function actually returns a tuple. Fix the docstring, run `python scripts/run.py preflight`, open a PR. That's it.

- **Add an example script** to a library's `examples/` folder — pick a use case from the library's guide that doesn't have an example yet.

  > *Example:* The msgpack guide explains stream-based `pack`/`unpack`, but there's no example showing how to save settings to a file and load them back. Write a `file_settings.py` in `libraries/msgpack/examples/` that does exactly that.

- **Improve test coverage** — run `python scripts/run.py test --libraries <name>`, check the `Missing` column in the coverage report, and write tests for uncovered lines.

  > *Example:* You run `python scripts/run.py test --libraries timing` and the coverage report shows lines 45–48 of `_ticks.py` aren't covered. Those lines handle a rare wraparound edge case. Write a test that triggers that path — now the library is more reliable because of you.

- **Try a library on your board** and report what happened — even a "it worked on my ESP32-S3" is valuable. Use the [board test report](https://github.com/ChuMicro/ChuMicro/issues/new?template=board_test_report.yml) template to share your results.

  > *Example:* You have a Raspberry Pi Pico. Install `chumicro-timing`, run the `heartbeat_blink.py` example, and file a board test report: "Tested on RP2040, CircuitPython 9.2 — heartbeat fires correctly at 1 Hz." That data point helps everyone.

Look for issues labeled [**good first issue**](https://github.com/ChuMicro/ChuMicro/labels/good%20first%20issue) — these are scoped, described, and ready to pick up.

## Reading guide

Start here, then pick the guide that matches your task:

| What you want to do | Read this |
|---|---|
| **Get the short version** | [Contributor Cheat Sheet](docs/contributing/cheat-sheet.md) — one page, everything you need |
| **Find something to work on** | [Good first contributions](#good-first-contributions) |
| **Set up and develop** | This page → then your [development environment guide](#development-environment) |
| **Configure real-board testing** | [Device Testing](docs/contributing/device-testing.md) |
| **Understand the code style** | [Style Guide](docs/contributing/style-guide.md) |
| **Open a pull request** | [Creating a Pull Request](docs/contributing/pull-requests.md) |
| **Add a new library** | [Adding a New Library](docs/contributing/new-library.md) |
| **Understand releases** | [Releases and Promotion](docs/contributing/releases.md) |
| **Use an AI coding agent** | [Working with Agents](docs/contributing/working-with-agents.md) |

Each page is self-contained for its topic. You don't need to read all of them — just the ones relevant to what you're doing.

## Prerequisites

| Tool | Version | Notes |
|------|---------|-------|
| Python | ≥ 3.11 | macOS: `brew install python`; Linux: system package; Windows: [python.org](https://python.org) |
| Git | any recent | |
| IDE (optional) | Any editor with a terminal | PyCharm, VS Code, Neovim, Zed, Emacs, Sublime — all work |

**Windows users:** use native Windows for editing, linting, and tests. Use WSL2 for unix-port cross-runtime checks. See [Development](README.md#development) in the README.

## Development environment

Pick whichever workflow you're comfortable with:

- **[PyCharm](docs/contributing/development-pycharm.md)** — run configurations, test explorer, source root management
- **[VS Code](docs/contributing/development-vscode.md)** — tasks, extensions, Pylance integration
- **[Other Editors / Command Line](docs/contributing/development-other-editors.md)** — Neovim, Zed, Emacs, Sublime, or anything with a terminal

If you plan to run `functional_tests/` on real boards, also read **[Device Testing](docs/contributing/device-testing.md)**. That guide covers `devices.yml`, `device-config.yml`, deploy modes, CLI usage, and IDE play-button routing.

You only need one. All three reach the same place.

## Quick start

This walks you through your entire first contribution — from fork to merged pull request. The example fixes a typo, but the same steps apply to any change.

### 1. Fork the repository

Only maintainers can push branches directly to the ChuMicro repository. Everyone else works through a **fork** — your own copy of the repository on GitHub. You push changes to your fork, then open a pull request asking the original repository to pull your changes in.

Go to **[github.com/ChuMicro/ChuMicro](https://github.com/ChuMicro/ChuMicro)** and click the **Fork** button (top right). GitHub creates a copy at `github.com/<your-username>/ChuMicro`.

### 2. Clone your fork

```bash
git clone https://github.com/<your-username>/ChuMicro.git
cd ChuMicro
```

Replace `<your-username>` with your GitHub username. For example, if your username is `octocat`:

```bash
git clone https://github.com/octocat/ChuMicro.git
```

### 3. Add the upstream remote

This connects your local clone to the original repository so you can pull future changes:

```bash
git remote add upstream https://github.com/ChuMicro/ChuMicro.git
```

You can verify both remotes are set up:

```bash
git remote -v
# origin    https://github.com/<your-username>/ChuMicro.git (fetch)
# upstream  https://github.com/ChuMicro/ChuMicro.git (fetch)
```

### 4. Set up the development environment

```bash
python scripts/prepare_workspace.py
source .venv/bin/activate
```

`prepare_workspace.py` auto-detects your environment: it reuses an active venv or conda env, reuses an existing `.venv` at the repo root, or creates a fresh `.venv` (via `uv` if available, else stdlib `venv`). It then installs every library and runs lint + host tests to confirm the install. When you see `Workspace is ready`, you're good.

> **Why this command and not `run.py setup`?** `prepare_workspace.py` is the first-time bootstrap — it's the only script that runs on a fresh clone before any third-party packages exist. Once your `.venv` is in place, `python scripts/run.py setup` handles everyday refreshes (new libraries, updated dependencies) and does the same install work idempotently. Use `prepare_workspace.py` once; use `run.py setup` forever after.

### 5. Verify everything works

```bash
python scripts/run.py preflight
```

You should see:

```
Preflight passed — required CI checks should pass.
```

If it fails, check that Python ≥ 3.11 is installed (`python --version`) and see your [development environment guide](#development-environment) for more troubleshooting.

### 6. Create a branch

Always work on a branch — never commit directly to `main`. Name the branch after what you're doing:

```bash
git checkout -b fix/my-first-change
```

The `fix/` prefix gives reviewers context at a glance. See [branching conventions](#branching-conventions) for more examples.

### 7. Make your change

Open the file in your editor and make the change. For example, fix a typo in a library's README:

```bash
# Open the file in your editor
code libraries/timing/README.md   # VS Code
# or: pycharm libraries/timing/README.md
# or: vim libraries/timing/README.md
```

Save the file when you're done.

### 8. Check your work

Run preflight to make sure your change doesn't break anything:

```bash
python scripts/run.py preflight
```

If it prints `Preflight passed`, you're good. If something fails, read the output — it tells you what went wrong and where.

### 9. Commit your change

Stage your files and commit. Git opens your default editor for the commit message:

```bash
git add -A
git commit
```

Write a message like:

```
Fix typo in timing README

"milisecond" → "millisecond" in the API summary table.
```

Use imperative mood in the subject line ("Fix", not "Fixed" or "Fixes"). See [commit messages](#commit-messages) for more guidance.

### 10. Push and open a pull request

Push your branch to your fork:

```bash
git push -u origin fix/my-first-change
```

Then open a pull request on GitHub:

1. Go to your fork on GitHub (`github.com/<your-username>/ChuMicro`). You'll see a banner saying your branch had recent pushes — click **Compare & pull request**.
2. GitHub knows your fork came from the original repository, so it automatically sets up the PR to merge your branch into `ChuMicro/ChuMicro`'s `main` branch. Verify the header reads **base repository: ChuMicro/ChuMicro** and **base: main**.
3. GitHub loads the PR template automatically. Fill in each section (summary, motivation, how to verify, etc.) and click **Create pull request**.

> **Why the GitHub UI?** The repository has a PR template with sections that help reviewers. The GitHub UI loads it automatically. If you prefer the CLI, use `gh pr create --template .github/PULL_REQUEST_TEMPLATE.md` to include the template so reviewers have the context they need.

CI runs automatically on your PR. All checks need to pass before a maintainer can merge. If something fails, click the failed check to see the log, fix it locally, and push again — CI re-runs automatically.

That's it — you've made your first contribution! 🎉

For the full details on any step, keep reading below.

## Keeping your fork in sync

Your fork doesn't update automatically when the original repository changes. Before starting new work, pull the latest `main` from upstream and push it to your fork:

```bash
git checkout main
git pull upstream main
git push origin main
```

This keeps your fork's `main` branch identical to the original. Always do this before creating a new branch.

### What if `main` moves while I'm working?

If other PRs merge while you're working on your branch, your branch falls behind. GitHub will show "This branch is out of date" on your PR. To catch up:

```bash
git checkout main
git pull upstream main
git push origin main
git checkout fix/my-first-change
git rebase main
```

If there are no conflicts, Git replays your changes on top of the updated `main`. Push the result:

```bash
git push --force-with-lease origin fix/my-first-change
```

If there are conflicts, Git pauses and tells you which files conflict. Open each file, look for the `<<<<<<<` / `>>>>>>>` markers, resolve them, then:

```bash
git add <resolved-file>
git rebase --continue
```

Repeat until the rebase finishes, then push with `--force-with-lease` as above.

> **`--force-with-lease`** is a safer version of `--force`. It refuses to overwrite the remote branch if someone else pushed to it since your last fetch — preventing you from accidentally losing work.

## Branching conventions

All work happens on branches off `main`. PRs target `main`. There is no `develop` branch.

Prefix your branch name with `fix/`, `docs/`, or `feature/` to give reviewers context at a glance, then add a short description of the work:

```bash
git checkout -b fix/timing-wraparound
git checkout -b docs/install-guide
git checkout -b feature/settings-lib
```

Use whatever prefix fits — the description matters more than the prefix.

After [syncing your fork](#keeping-your-fork-in-sync), create a branch:

```bash
git checkout -b feature/my-change
```

## Making changes

### Preflight

Before opening a PR, run preflight:

```bash
python scripts/run.py preflight
```

If it prints `Preflight passed`, you're good — CI will pass too. That's the only command you need to remember. Everything else below is what preflight checks behind the scenes.

<details>
<summary>What preflight checks (expand for details)</summary>

- **Test coverage** per library (85% branch coverage). Run individually: `python scripts/run.py test --libraries <name>`
- **Scripts infrastructure tests pass.** Run individually: `python scripts/run.py test-scripts`
- **No lint errors.** Run individually: `python scripts/run.py lint`
- **Examples must parse.** Run individually: `python scripts/run.py verify-examples --libraries <name>`
- **Docs must build.** Run individually: `python scripts/run.py docs --libraries <name>`
- **No API breakage** without a VERSION bump. CI runs `check-api` and `check-version` automatically.
- **Cross-runtime compatibility.** CI runs your code under MicroPython and CircuitPython unix ports.

</details>

> **Coverage note:** The test suite catches real edge cases that lower thresholds miss. If coverage fails on code you didn't change, that's not your fault — note it in the PR description. A maintainer can help fill the gap or mark an exception. Don't let someone else's uncovered code block your contribution.

### Device testing

Device testing is **optional**. If your change could behave differently on a real board than in tests, including console output from a device is appreciated but never required to open a PR. If you're not sure, submit the PR without it and note that in the description — a reviewer will tell you if it's needed.

**Most contributions don't need this.** Docs-only, test-only, infrastructure, and trivial fixes are exempt. Libraries with no hardware interaction (like `compat` and `msgpack`) are also exempt. See the [device testing guide](docs/contributing/device-testing.md) for setup and workflow, and the [PR guide's device-testing section](docs/contributing/pull-requests.md#device-testing) for what to include when you do test.

When you do want real-board coverage, the current workflow is:

1. Run `python scripts/run.py setup` once to generate local `devices.yml` and `device-config.yml` files.
2. Fill in your board details in `devices.yml` and any shared environment data in `device-config.yml`. The top-level `defaults:` block in `devices.yml` picks the runtime(s) and per-runtime board IDs that bare `test-device` and IDE play buttons target.
3. Run `python scripts/run.py test-device` on the defaults-backed target set, or use one of the scoping flags (`--library`, `--file`, `--function`, `--runtime`, `--deploy-mode`) to narrow the run. Full flag reference and pytest-direct usage are in [Device testing](docs/contributing/device-testing.md).
4. For IDE-driven runs, target an explicit `functional_tests/` file, directory, or function — the pytest device plugin routes it to the board selected by `devices.yml`.

The full schema and workflow live in the [device testing guide](docs/contributing/device-testing.md).

### End-of-session housekeeping

If you've been working through a longer session, the **[end-of-session checklist](.github/skills/end-of-session/SKILL.md)** has the full cleanup pass — preflight, VERSION bump check, IDE config sync, planning-doc audit, and a clean-tree verification. Most one-off contributions don't need it; longer or multi-PR sessions do.

### Commit messages

Write clear commit messages that explain *why*, not just *what*. Git opens your default editor when you run `git commit`:

```bash
git add -A
git commit
```

Example message:

```
Fix wraparound bug in ticks_diff

The previous implementation didn't handle the case where ticks_ms
wraps past 2^30. Added boundary tests to verify.

Affects: timing
```

Use imperative mood in the subject line. Name affected libraries in the body.

## Pull request workflow

The [quick start](#quick-start) covers the basic flow. For a detailed walkthrough — PR templates, CI check details, review process — see [Creating a Pull Request](docs/contributing/pull-requests.md).

### VERSION bumps

Libraries use [semantic versioning](https://semver.org/). If your PR changes library source code (not just tests, docs, or infra), bump the `VERSION` file:

| Change type | Bump | Example |
|---|---|---|
| Bug fix, no API change | Patch | `0.1.15` → `0.1.16` |
| New feature, backward-compatible | Minor | `0.1.15` → `0.2.0` |
| Breaking API change | Major | `0.1.15` → `1.0.0` |

CI catches this — if you change source files without bumping VERSION, `check-version` will let you know.

## Publishing and releases

> **Full details:** See [Releases and Promotion](docs/contributing/releases.md) for the complete release pipeline.

When your PR merges to `main` with a VERSION bump, the library is **automatically published as an experimental release** — to PyPI, the experimental bundle repo, and experimental docs. No manual steps needed.

**Stable promotion** is a separate step. When you believe an experimental release is ready for production:

1. Open a [Stable Promotion Request](https://github.com/ChuMicro/ChuMicro/issues/new?template=stable_promotion.yml) issue
2. A maintainer verifies and runs the promotion workflow
3. The library is published to the stable PyPI package, stable bundle repo, and stable docs

## Adding a new library

> **Full guide:** See [Adding a New Library](docs/contributing/new-library.md) for the complete lifecycle from idea to published package.

**Before you scaffold:** read [new-library.md § Before you start](docs/contributing/new-library.md#before-you-start) — a 2-minute scope check (issues, discussions, `plans/roadmap.md`, `plans/decisions/`) saves rewrites if your idea overlaps with planned work or settled design choices.

The short version:

```bash
python scripts/run.py new-library my-thing   # scaffolds everything
# ... write code, tests, docs, examples ...
python scripts/run.py preflight              # must pass
# ... open PR, get reviewed, merge ...
# Experimental release happens automatically on merge
```

Libraries must work on all three runtimes (CircuitPython, MicroPython, CPython) unless platform-restricted via `pyproject.toml`. The tooling checks this automatically.

## Project rules (quick reference)

These aren't arbitrary — each one traces to a design decision with rationale. The **[Style Guide](docs/contributing/style-guide.md)** covers naming, annotations, docstrings, and formatting in detail. Browse `plans/decisions/` if you're curious about the deeper reasoning.

| Rule | Why |
|---|---|
| PEP 8 + descriptive names | The linter catches this for you — see the [Style Guide](docs/contributing/style-guide.md) |
| No `async`/`await` | The tick-based runner keeps everything visible in a single loop — easier to test, debug, and inspect on resource-constrained boards. `asyncio` on microcontrollers is limited and not bug-free. ([Decision 0014](plans/decisions/0014-runner-pattern.md)) |
| Constructor injection for I/O | Testability with fakes and dependency injection ([Decision 0010](plans/decisions/0010-library-testability.md)) |
| Per-library `pytest` runs | Avoids test-directory collisions ([Decision 0009](plans/decisions/0009-per-library-test-runs.md)) |
| `const()` / `memoryview` in library code | Memory efficiency on microcontrollers (not required in `scripts/` or `support/`). You can add these later — correctness first. |

## Common mistakes

| Symptom | Cause | Fix |
|---|---|---|
| `ImportError` when running `pytest` directly | Bare `pytest` doesn't know about the per-library layout | Use `python scripts/run.py test --libraries <name>` instead |
| A `functional_tests/` play button says no device is configured | `devices.yml` is missing, empty, or points at the wrong board IDs | Run `python scripts/run.py setup`, then update `devices.yml` defaults and device entries. See [Device Testing](docs/contributing/device-testing.md) |
| `check-version` fails but you only changed tests | CI checks source changes under `src/` | No VERSION bump needed for test-only, docs-only, or infra changes — delete the failing step's output note in your PR |
| Coverage fails on code you didn't touch | Pre-existing gap in another file | Note it in the PR description — a maintainer can help fill the gap or mark an exception |
| `griffe warnings detected` in docs build | Missing type annotation on a function parameter | Add the type to the signature: `def foo(x: int)` — docstrings carry descriptions only |
| Merge conflicts after pushing | `main` moved while you were working | [Rebase your branch](#what-if-main-moves-while-im-working) onto the latest `main` |
| PyCharm/VS Code shows red import underlines | IDE configs are stale | Run `python scripts/run.py sync-ide`, then reload the project |
| PyCharm changed `.idea/chumicro.iml` after you picked an interpreter | PyCharm rewrites the tracked module file while adjusting SDK/module state | Click the **Sync IDE** run configuration (or run `python scripts/run.py sync-ide`) before committing so the managed source-root layout is restored. `setup` / `prepare_workspace` do the same regeneration for a fuller reset |

## Contributor FAQ

**Do I need a device to contribute?**
No. Most contributions don't need device testing. If yours does and you don't have a board, say so in the PR — a maintainer can help.

**How do I set up `devices.yml`?**
Run `python scripts/run.py setup`, then edit the generated `devices.yml` and `device-config.yml` files. `devices.yml` picks the default MicroPython/CircuitPython boards and deploy mode; `device-config.yml` carries shared values like WiFi credentials. See [Device Testing](docs/contributing/device-testing.md) for the schema and examples.

**What if coverage fails on code I didn't write?**
Note it in the PR description. A maintainer can help fill the gap or mark an exception. Don't let someone else's uncovered code block your contribution.

**Do I need to read all the docs before contributing?**
No. The [Quick Start](#quick-start) and `preflight` are all you need for your first PR. The rest is reference material for when you need it.

**Can I use `async`/`await`?**
Not in library code. On a microcontroller with 256 KB RAM, an event loop adds overhead and hides state. The tick-based pattern keeps everything visible in a single loop — easier to debug with print statements when you're connected to a serial console. Additionally, `asyncio` on CircuitPython and MicroPython is limited and not exactly bug-free. See [Decision 0014](plans/decisions/0014-runner-pattern.md) for the full reasoning.

**Why do I have to spell out `error` instead of `err`?**
We use full words so everyone can read the code without looking things up — newcomers, multilingual developers, and non-native English speakers shouldn't need a glossary. The linter tells you exactly what to write, so the cost is a few extra keystrokes.  Single-letter for-loop targets like `for i in range(10)` are fine. See [Decision 0022](plans/decisions/0022-naming-conventions.md) for the full reasoning.

## Project decisions

Major design choices live in [`plans/decisions/`](plans/decisions/) — each file explains what was decided, why, and when. Current direction lives in [`plans/roadmap.md`](plans/roadmap.md). Unresolved threads live in [`plans/open-questions.md`](plans/open-questions.md). **Search these before proposing structural changes** — if your idea was already considered, the decision doc tells you the reasoning and whether circumstances have changed.

## Getting help

- **Have a question?** Start a [discussion](https://github.com/ChuMicro/ChuMicro/discussions) — Q&A, ideas, and show-and-tell
- **Something broken?** Open a [bug report](https://github.com/ChuMicro/ChuMicro/issues/new?template=bug_report.yml)
- **Have an idea?** Open a [feature request](https://github.com/ChuMicro/ChuMicro/issues/new?template=feature_request.yml)
- **Want to try an AI agent?** See [Working with Agents](docs/contributing/working-with-agents.md) — agents handle a lot of the mechanical work in this project
- **Questions about decisions?** Browse [`plans/decisions/`](plans/decisions/) — they explain *why* things work the way they do

## License

By contributing, you agree that your contributions will be licensed under the [MIT License](LICENSE).
