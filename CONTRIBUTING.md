# Contributing to ChuMicro

<img src="support/docs/chumicro_tip.png" align="left" width="64" style="margin-right: 16px; margin-bottom: 8px;">

Welcome.  ChuMicro is an open platform for cross-runtime Python libraries targeting CircuitPython, MicroPython, and CPython.  Whether you're fixing a typo, adding tests, or publishing your own library — you belong here.

**You don't need to be an expert.**  The tooling handles most of the hard parts (coverage, linting, cross-runtime checks, release automation).  If you can run a few commands and follow the guidelines, you can contribute.

<br clear="left">

> ⚡ **Short on time?** The **[Contributor Cheat Sheet](docs/contributing/cheat-sheet.md)** is one page with everything you need — setup, workflow, and the only command you have to remember.

## Good first contributions

Not sure where to start?  These are real ways to contribute that don't require deep knowledge of the codebase:

- **Fix a typo or clarify a sentence** in any README, guide, or docstring — docs-only PRs skip most CI checks.
- **Add an example script** to a library's `examples/` folder — pick a use case the library's guide explains but doesn't demo.
- **Improve test coverage** — run `python scripts/run.py test --libraries <name>`, check the `Missing` column, and write tests for uncovered lines.
- **Try a library on your board** and report what happened — even "it worked on my ESP32-S3" is valuable.  Use the [board test report](https://github.com/ChuMicro/ChuMicro/issues/new?template=board_test_report.yml) template.

Look for issues labeled [**good first issue**](https://github.com/ChuMicro/ChuMicro/labels/good%20first%20issue) — scoped, described, ready to pick up.

## Reading guide

| What you want to do | Read this |
|---|---|
| **Get the short version** | [Contributor Cheat Sheet](docs/contributing/cheat-sheet.md) — one page, everything you need |
| **Find something to work on** | [Good first contributions](#good-first-contributions) |
| **Set up and develop** | This page → then your [development environment guide](#development-environment) |
| **Configure real-board testing** | [Device Testing](docs/contributing/device-testing.md) |
| **Understand devices.yml / workspace.yml / secrets.toml** | [Workspace, devices, and secrets](docs/contributing/config-files.md) |
| **Understand the code style** | [Style Guide](docs/contributing/style-guide.md) |
| **Open a pull request** | [Creating a Pull Request](docs/contributing/pull-requests.md) |
| **Add a new library** | [Adding a New Library](docs/contributing/new-library.md) |
| **Add a host-only workbench tool** | [Workbench — host-only tools](docs/contributing/workbench.md) |
| **Understand releases** | [Releases and Promotion](docs/contributing/releases.md) |
| **Use an AI coding agent** | [Working with Agents](docs/contributing/working-with-agents.md) |
| **Recover from a broken state** | [Troubleshooting](docs/troubleshooting/) — macOS CIRCUITPY wedge, stale mounts |

Each page is self-contained.  You don't need to read all of them — just the ones relevant to what you're doing.

## Prerequisites

| Tool | Version | Notes |
|------|---------|-------|
| Python | ≥ 3.11 | macOS: `brew install python`; Linux: system package; Windows: [python.org](https://python.org) |
| Git | any recent | |
| IDE (optional) | Any editor with a terminal | PyCharm, VS Code, Neovim, Zed, Emacs, Sublime — all work |

**Windows users:** use native Windows for editing, linting, and tests.  Use WSL2 for unix-port cross-runtime checks.

## Development environment

Pick whichever workflow you're comfortable with:

- **[PyCharm](docs/contributing/development-pycharm.md)** — run configurations, test explorer, source root management.
- **[VS Code](docs/contributing/development-vscode.md)** — tasks, extensions, Pylance integration.
- **[Other Editors / Command Line](docs/contributing/development-other-editors.md)** — Neovim, Zed, Emacs, Sublime, anything with a terminal.

You only need one of the three — they all reach the same place.  If you'll run `functional_tests/` on real boards, also read **[Device Testing](docs/contributing/device-testing.md)**.

## Quick start

A typical first contribution, end-to-end:

```bash
# 1. Fork on GitHub (top-right Fork button), then clone your fork
git clone https://github.com/<your-username>/ChuMicro.git
cd ChuMicro
git remote add upstream https://github.com/ChuMicro/ChuMicro.git

# 2. Bootstrap (one-time on a fresh clone)
python scripts/prepare_workspace.py
source .venv/bin/activate

# 3. Verify
python scripts/run.py preflight

# 4. Branch, edit, run preflight, commit
git checkout -b fix/my-change
# ... edit files ...
python scripts/run.py preflight
git add -A && git commit                # imperative subject, explain why

# 5. Push and open a PR on GitHub
git push -u origin fix/my-change
```

`prepare_workspace.py` is the first-time bootstrap — it auto-detects or creates `.venv/`, installs every library, and runs lint + host tests to confirm.  After that, `python scripts/run.py setup` handles everyday refreshes (new libraries, updated deps).  Use `prepare_workspace.py` once; use `run.py setup` forever after.

CI runs automatically on your PR.  All required checks need to pass before a maintainer merges.  If something fails, click the failed check, fix it locally, push again — CI re-runs.

## Keeping your fork in sync

Before starting new work, pull the latest `main` from upstream:

```bash
git checkout main && git pull upstream main && git push origin main
```

If `main` moves while your branch is open, rebase: `git checkout my-branch && git rebase main && git push --force-with-lease`.  See [Git's rebase docs](https://git-scm.com/book/en/v2/Git-Branching-Rebasing) for conflict resolution.

## Branching

All work happens on branches off `main`; PRs target `main`.  No `develop` branch.  Prefix branch names with `fix/`, `docs/`, or `feature/` to give reviewers a glance at intent.

## Preflight

Before opening a PR:

```bash
python scripts/run.py preflight
```

If it prints `Preflight passed`, CI will pass too.  That's the only command you have to remember.

> **Coverage note:** if coverage fails on code you didn't change, that's not your fault — note it in the PR description.  A maintainer can help fill the gap or mark an exception.

<details>
<summary>What preflight checks (click to expand)</summary>

- **Test coverage** per library (85% gate, line + branch).  Run individually: `python scripts/run.py test --libraries <name>`.
- **Scripts infrastructure tests:** `python scripts/run.py test-scripts`.
- **No lint errors:** `python scripts/run.py lint`.
- **Examples must parse:** `python scripts/run.py verify-examples --libraries <name>`.
- **Docs must build:** `python scripts/run.py docs --libraries <name>`.
- **No API breakage** without a VERSION bump (CI runs `check-api` and `check-version`).
- **Cross-runtime compatibility:** CI runs your code under MicroPython and CircuitPython unix ports.

</details>

## Device testing

Device testing is **optional**.  Most contributions don't need it — docs-only, test-only, infrastructure, and trivial fixes are exempt.  When you do want real-board coverage, run `python scripts/run.py setup` to generate an empty `devices.yml`, register a board with `python scripts/run.py add-device <id> --address <port>` (probes hardware identity + fills in defaults), then `python scripts/run.py test-libraries-functional [--library <name>]`.  See **[Device Testing](docs/contributing/device-testing.md)** for the full workflow.

## Commit messages

Imperative subject; body explains why; name affected libraries.  Full conventions + examples in [Creating a Pull Request](docs/contributing/pull-requests.md).

## VERSION bumps

Libraries use [semantic versioning](https://semver.org/).  If your PR changes library source code (not just tests, docs, or infra), bump the `VERSION` file:

| Change type | Bump | Example |
|---|---|---|
| Bug fix, no API change | Patch | `0.1.15` → `0.1.16` |
| New feature, backward-compatible | Minor | `0.1.15` → `0.2.0` |
| Breaking API change | Major | `0.1.15` → `1.0.0` |

CI catches this automatically — `check-version` will let you know if you forgot.

## Publishing

When your PR merges to `main` with a VERSION bump, the library auto-publishes as an **experimental release** to PyPI, the experimental bundle, and experimental docs — no manual steps.

**Stable promotion** is a separate maintainer step.  Open a [Stable Promotion Request](https://github.com/ChuMicro/ChuMicro/issues/new?template=stable_promotion.yml) when an experimental release is ready.  See [Releases and Promotion](docs/contributing/releases.md) for the full pipeline.

## Adding a new package

`python scripts/run.py new-library <name>` scaffolds a device library under `libraries/` (cross-runtime, ships to PyPI + the bundle).  For host-only workbench tools under `workbench/` see [`docs/contributing/workbench.md`](docs/contributing/workbench.md).  Before you scaffold, skim [Adding a New Library § Before you start](docs/contributing/new-library.md#before-you-start) for the 2-minute scope check.

## Project rules

These aren't arbitrary — each traces to a design decision with rationale.  The **[Style Guide](docs/contributing/style-guide.md)** covers naming, annotations, docstrings, and formatting in detail.

| Rule | Why |
|---|---|
| PEP 8 + descriptive names | The linter catches this — see the [Style Guide](docs/contributing/style-guide.md). |
| Tick-based runner instead of `async`/`await` | Every state change is visible from `print()` on a serial console; nothing hides inside an event loop.  Transparent state matters more than syntactic concurrency on a board where serial is your only window.  ([Decision 0014](plans/decisions/0014-runner-pattern.md)) |
| Constructor injection for I/O | Testability with fakes ([Decision 0010](plans/decisions/0010-library-testability.md)). |
| Per-library `pytest` runs | Avoids test-directory collisions ([Decision 0009](plans/decisions/0009-per-library-test-runs.md)). |
| `const()` / `memoryview` in library code | Memory efficiency on microcontrollers.  Add later if needed — correctness first. |

## Common mistakes

| Symptom | Cause | Fix |
|---|---|---|
| Tests pass via `pytest` but `preflight` fails coverage | Bare `pytest` runs your tests but doesn't enforce the per-library coverage gate | Use `python scripts/run.py test --libraries <name>` for commit-gating runs |
| `functional_tests/` says no device is configured | `devices.yml` is missing or has wrong board IDs | Run `python scripts/run.py setup`, then update `devices.yml`.  See [Device Testing](docs/contributing/device-testing.md) |
| `check-version` fails but you only changed tests | CI checks source changes under `src/` | No VERSION bump needed for test-only / docs-only / infra changes — note in PR description |
| Coverage fails on code you didn't touch | Pre-existing gap | Note in PR description; a maintainer can help |
| `griffe warnings detected` in docs build | Missing type annotation | Add types to function signatures: `def foo(x: int)` — docstrings carry descriptions |
| Merge conflicts after pushing | `main` moved while you were working | Rebase your branch onto the latest `main` |
| PyCharm/VS Code shows red import underlines | IDE configs are stale | `python scripts/run.py sync-ide`, then reload |

## Project decisions

Major design choices live in [`plans/decisions/`](plans/decisions/) — each file explains what was decided, why, and when.  Current direction lives in [`plans/next-up.md`](plans/next-up.md) and [`plans/workstreams/`](plans/workstreams/).  When debugging a class of problem you suspect someone else has already hit, search `git log` for the area you're touching — workarounds for hardware / runtime gotchas live in inline code comments next to the workaround, with the originating commit message carrying the rationale.

**Search these before proposing structural changes** — if your idea was already considered, the decision doc tells you the reasoning and whether circumstances have changed.

## Getting help

- **Question?** [Discussion](https://github.com/ChuMicro/ChuMicro/discussions)
- **Something broken?** [Bug report](https://github.com/ChuMicro/ChuMicro/issues/new?template=bug_report.yml)
- **Have an idea?** [Feature request](https://github.com/ChuMicro/ChuMicro/issues/new?template=feature_request.yml)
- **Want to try an AI agent?** [Working with Agents](docs/contributing/working-with-agents.md)

## License

By contributing, you agree your contributions will be licensed under the [MIT License](LICENSE).
