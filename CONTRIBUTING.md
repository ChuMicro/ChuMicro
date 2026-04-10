# Contributing to Chumicro

Welcome! Chumicro is an open platform for cross-runtime Python libraries targeting CircuitPython, MicroPython, and CPython. Whether you're fixing a typo, adding tests, or publishing your own library — you belong here.

**You don't need to be an expert.** The tooling handles most of the hard parts (coverage, linting, cross-runtime checks, release automation). If you can run a few commands and follow the guidelines, you can contribute.

## Reading guide

Start here, then pick the guide that matches your task:

| What you want to do | Read this |
|---|---|
| **Find something to work on** | [Good first contributions](#good-first-contributions) |
| **Set up and develop** | This page → then your [development environment guide](#development-environment) |
| **Open a pull request** | [Creating a Pull Request](docs/contributing/pull-requests.md) |
| **Add a new library** | [Adding a New Library](docs/contributing/new-library.md) |
| **Understand the codebase** | [How the Codebase Works](docs/contributing/architecture.md) |
| **Understand releases** | [Releases and Promotion](docs/contributing/releases.md) |
| **Use an AI coding agent** | [Working with Agents](docs/contributing/working-with-agents.md) |

Each page is self-contained for its topic. You don't need to read all of them — just the ones relevant to what you're doing.

## Prerequisites

| Tool | Version | Notes |
|------|---------|-------|
| Python | ≥ 3.11 | macOS: `brew install python`; Linux: system package; Windows: [python.org](https://python.org) |
| Git | any recent | |
| IDE (optional) | Any editor with a terminal | PyCharm, VS Code, Neovim, Zed, Emacs, Sublime — all work |

**Windows users:** use native Windows for editing, linting, and tests. Use WSL2 for unix-port cross-runtime checks. See [Development setup](README.md#development-setup) in the README.

## Development environment

The project supports three workflows — pick whichever you're comfortable with. Each guide covers setup, running tasks, interpreting output (both success and failure), and a validation checklist:

- **[Command Line](docs/contributing/development-cli.md)** — no IDE required, full control
- **[PyCharm](docs/contributing/development-pycharm.md)** — run configurations, test explorer, source root management
- **[VS Code](docs/contributing/development-vscode.md)** — tasks, extensions, Pylance integration
- **[Other Editors](docs/contributing/development-other-editors.md)** — Neovim, Zed, Emacs, Sublime, or anything with a terminal

You only need one. All four reach the same place.

## Quick start

```bash
# 1. Fork and clone
git clone https://github.com/<your-username>/ChuMicro.git
cd ChuMicro

# 2. Set up the development environment
python scripts/prepare_workspace.py --create-venv  # or without --create-venv if you have one

# 3. Verify everything works
python scripts/run.py preflight 2>&1 | tail -5
# Expected: "Preflight passed — required CI checks should pass."
```

If preflight passes, you're ready. If not, see your development environment guide for troubleshooting.

## Branching conventions

All work happens on branches off `main`. PRs target `main`. There is no `develop` branch.

| Branch type | Naming | When to use | Example |
|---|---|---|---|
| **Topic** | `fix/<description>` or `docs/<description>` | Bug fixes, doc changes, small improvements | `fix/heartbeat-wraparound` |
| **Feature** | `feature/<description>` | New features, new libraries, larger work | `feature/settings-library` |
| **Release** | `release/<lib>-v<major.minor>.x` | Hotfix against an older stable tag (rare) | `release/timing-v0.2.x` |

Create a branch:

```bash
git checkout main
git pull origin main
git checkout -b feature/my-change
```

## Making changes

### Key rules

Before opening a PR, run preflight:

```bash
python scripts/run.py preflight 2>&1 | tail -5
```

If it prints `Preflight passed`, you're good — CI will pass too. That's the only command you need to remember. Everything else below is what preflight checks behind the scenes.

<details>
<summary>What preflight checks (expand for details)</summary>

- **94% test coverage** per library. Run individually: `python scripts/run.py test --libraries <name>`
- **No lint errors.** Run individually: `python scripts/run.py lint`
- **Examples must parse.** Run individually: `python scripts/run.py verify-examples --libraries <name>`
- **Docs must build.** Run individually: `python scripts/run.py docs --libraries <name>`
- **No API breakage** without a VERSION bump. CI runs `check-api` and `check-version` automatically.
- **Cross-runtime compatibility.** CI runs your code under MicroPython and CircuitPython unix ports.

</details>

> **Coverage note:** The 94% gate catches real edge cases that 90% missed — we tried the lower bar and regretted it. If your PR trips the coverage gate on code you didn't change, note it in the PR description. A maintainer can help fill the gap or mark an exception. Don't let someone else's uncovered code block your contribution.

### Device testing

PRs that change library code need evidence that the code works on a real device — console output from running on hardware, plus the board and runtime version used. This is how we catch issues that CI's unix-port checks can't.

**Most contributions don't need this.** Docs-only, test-only, infrastructure, and trivial fixes are exempt. Libraries with no hardware interaction (like `compat` and `msgpack`) are also exempt. See [Device Testing](docs/contributing/pull-requests.md#device-testing) in the PR guide for full details.

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

> **Full walkthrough:** See [Creating a Pull Request](docs/contributing/pull-requests.md) for step-by-step instructions.

The short version:

1. Push your branch: `git push -u origin feature/my-change`
2. Open a PR on GitHub targeting `main`
3. CI runs automatically — all checks must pass
4. A maintainer reviews and merges

### VERSION bumps

Libraries use [semantic versioning](https://semver.org/). If your PR changes library source code (not just tests, docs, or infra), bump the `VERSION` file:

| Change type | Bump | Example |
|---|---|---|
| Bug fix, no API change | Patch | `0.1.15` → `0.1.16` |
| New feature, backward-compatible | Minor | `0.1.15` → `0.2.0` |
| Breaking API change | Major | `0.1.15` → `1.0.0` |

CI enforces this — if you change source files without bumping VERSION, `check-version` will fail.

When you bump VERSION for a user-visible change (new feature, changed behavior, bug fix that affects usage), add a bullet to the "What's new" section in `docs/guide.md`. Internal refactors and test-only changes don't need an entry.

## Publishing and releases

> **Full details:** See [Releases and Promotion](docs/contributing/releases.md) for the complete release pipeline.

When your PR merges to `main` with a VERSION bump, the library is **automatically published as an experimental release** — to PyPI, the experimental bundle repo, and experimental docs. No manual steps needed.

**Stable promotion** is a separate step. When you believe an experimental release is ready for production:

1. Open a [Stable Promotion Request](https://github.com/ChuMicro/ChuMicro/issues/new?template=stable_promotion.yml) issue
2. A maintainer verifies and runs the promotion workflow
3. The library is published to the stable PyPI package, stable bundle repo, and stable docs

## Adding a new library

> **Full guide:** See [Adding a New Library](docs/contributing/new-library.md) for the complete lifecycle from idea to published package.

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

These aren't arbitrary — each one traces to a design decision with rationale. Browse `plans/decisions/` if you're curious about the reasoning.

| Rule | Why |
|---|---|
| No `async`/`await` | CircuitPython ships a pure-Python asyncio (Adafruit fork, frozen into firmware — the C `_asyncio` module is never compiled in). MicroPython's asyncio has C-backed task scheduling but a Python event loop. Both are a single global loop with no scheduling visibility, no priority control, and limited networking support. Constructor injection and testability are awkward because the loop owns the call stack. The tick-based runner gives you the same periodic-dispatch capability with explicit scheduling you can inspect and test. ([Decision 0014](plans/decisions/0014-runner-pattern.md)) |
| Constructor injection for I/O | Testability without mocking things you don't own ([Decision 0010](plans/decisions/0010-library-testability.md)) |
| Per-library `pytest` runs | Avoids test-directory collisions ([Decision 0009](plans/decisions/0009-per-library-test-runs.md)) |
| Standard annotations, no `typing` imports | Both embedded runtimes parse annotations correctly but don't have the `typing` module. Use annotations with built-in types and PEP 604/585 syntax (`int | None`, `list[int]`). Docstrings carry descriptions only — griffe reads types from annotations. ([Decision 0021](plans/decisions/0021-docstring-type-policy.md)) |
| f-strings for formatting | Use `f"value={x}"` — not `%` or `.format()`. Consistent and readable across all three runtimes |
| Descriptive names, no single-letter variables | No single-letter variables (except `_`). Spell out `error`, `file`, `index` — not `e`, `f`, `i`. Enforced by `CHU001` linter rule — `python scripts/run.py lint` catches violations ([Decision 0022](plans/decisions/0022-naming-conventions.md)) |
| `const()` / `memoryview` in library code | Memory efficiency on microcontrollers — see [examples](docs/contributing/new-library.md#memory-efficient-patterns) (not required in `scripts/` or `support/`) |

## Common mistakes

| Symptom | Cause | Fix |
|---|---|---|
| `ImportError` when running `pytest` directly | Bare `pytest` doesn't know about the per-library layout | Use `python scripts/run.py test --libraries <name>` instead |
| `check-version` fails but you only changed tests | CI gates source changes under `src/` | No VERSION bump needed for test-only, docs-only, or infra changes — delete the failing step's output note in your PR |
| Coverage fails on code you didn't touch | Pre-existing gap in another file | Note it in the PR description — a maintainer can help fill the gap or mark an exception |
| `griffe warnings detected` in docs build | Missing type annotation on a function parameter | Add the type to the signature: `def foo(x: int)` — docstrings carry descriptions only |
| Merge conflicts after pushing | `main` moved while you were working | `git pull --rebase origin main`, resolve conflicts, force-push your branch |
| PyCharm/VS Code shows red import underlines | IDE configs are stale | Run `python scripts/run.py sync-ide`, then reload the project |

## Getting help

- **Have a question?** Start a [discussion](https://github.com/ChuMicro/ChuMicro/discussions) — Q&A, ideas, and show-and-tell
- **Something broken?** Open a [bug report](https://github.com/ChuMicro/ChuMicro/issues/new?template=bug_report.yml)
- **Have an idea?** Open a [feature request](https://github.com/ChuMicro/ChuMicro/issues/new?template=feature_request.yml)
- **Want to try an AI agent?** See [Working with Agents](docs/contributing/working-with-agents.md) — agents handle a lot of the mechanical work in this project
- **Questions about decisions?** Browse [`plans/decisions/`](plans/decisions/) — they explain *why* things work the way they do

## Good first contributions

Not sure where to start? These are real ways to contribute that don't require deep knowledge of the codebase:

- **Fix a typo or clarify a sentence** in any README, guide, or docstring — docs-only PRs skip most CI gates.
- **Add an example script** to a library's `examples/` folder — pick a use case from the library's guide that doesn't have an example yet.
- **Improve test coverage** — run `python scripts/run.py test --libraries <name>`, check the `Missing` column in the coverage report, and write tests for uncovered lines.
- **Try a library on your board** and report what happened — even a "it worked on my ESP32-S3" comment on an issue is valuable.

Look for issues labeled [**good first issue**](https://github.com/ChuMicro/ChuMicro/labels/good%20first%20issue) — these are scoped, described, and ready to pick up.

## License

By contributing, you agree that your contributions will be licensed under the [MIT License](LICENSE).
