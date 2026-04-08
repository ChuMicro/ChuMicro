# Contributing to Chumicro

Welcome! Chumicro is an open platform for cross-runtime Python libraries targeting CircuitPython, MicroPython, and CPython. Whether you're fixing a typo, adding tests, or publishing your own library — you belong here.

**You don't need to be an expert.** The tooling handles most of the hard parts (coverage, linting, cross-runtime checks, release automation). If you can run a few commands and follow the guidelines, you can contribute.

**Agents are welcome too.** If you're working with an AI coding agent, point it at [`AGENTS.md`](AGENTS.md) for the full rule set. Agents are especially helpful for writing tests (the 94% coverage gate is real) and generating documentation.

## Prerequisites

| Tool | Version | Notes |
|------|---------|-------|
| Python | ≥ 3.11 | macOS: `brew install python`; Linux: system package; Windows: [python.org](https://python.org) |
| Git | any recent | |
| IDE (optional) | PyCharm, VS Code, or CLI | All three are fully supported |

**Windows users:** use native Windows for editing, linting, and tests. Use WSL2 for unix-port cross-runtime checks. See [Getting started](README.md#getting-started) in the README.

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

If preflight passes, you're ready. If not, check the output for missing dependencies.

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

These are enforced by CI — your PR won't merge without them:

- **94% test coverage** per library. Run: `python scripts/run.py test --libraries <name>`
- **No lint errors.** Run: `python scripts/run.py lint`
- **Examples must parse.** Run: `python scripts/run.py verify-examples --libraries <name>`
- **Docs must build.** Run: `python scripts/run.py docs --libraries <name>`
- **No API breakage** without a VERSION bump. CI runs `check-api` and `check-version` automatically.
- **Cross-runtime compatibility.** CI runs your code under MicroPython and CircuitPython unix ports.

### Commit messages

Write commit messages to a file — never use `git commit -m` (breaks on special characters in zsh):

```bash
# Write the message
cat > .scratch/commit-msg.txt << 'EOF'
Fix wraparound bug in ticks_diff

The previous implementation didn't handle the case where ticks_ms
wraps past 2^30. Added boundary tests to verify.

Affects: timing
EOF

# Commit
git add -A && git commit -F .scratch/commit-msg.txt
```

Use imperative mood in the subject line. Name affected libraries in the body.

## Pull request workflow

> **Detailed walkthrough:** See [Creating a Pull Request](docs/contributing/pull-requests.md) for a step-by-step guide with expected output at each stage.

1. Push your branch: `git push -u origin feature/my-change`
2. Open a PR on GitHub targeting `main`
3. Fill in the [PR template](.github/PULL_REQUEST_TEMPLATE.md) — Summary, Motivation, Changes, How to verify, Version impact
4. CI runs automatically (lint, test, build, docs, cross-runtime checks, version-check, api-check)
5. A maintainer reviews and merges

### VERSION bumps

If your PR changes library source code (not just tests, docs, or infra), bump the `VERSION` file:

| Change type | Bump | Example |
|---|---|---|
| Bug fix, no API change | Patch | `0.1.15` → `0.1.16` |
| New feature, backward-compatible | Minor | `0.1.15` → `0.2.0` |
| Breaking API change | Major | `0.1.15` → `1.0.0` |

CI enforces this — if you change source files without bumping VERSION, `check-version` will fail.

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

| Rule | Why |
|---|---|
| No `async`/`await` | Microcontrollers use tick-based scheduling ([Decision 0014](plans/decisions/0014-runner-pattern.md)) |
| Constructor injection for I/O | Testability without mocking things you don't own ([Decision 0010](plans/decisions/0010-library-testability.md)) |
| Per-library `pytest` runs | Avoids test-directory collisions ([Decision 0009](plans/decisions/0009-per-library-test-runs.md)) |
| Docstring types, not annotations | CircuitPython/MicroPython don't reliably support annotations ([Decision 0021](plans/decisions/0021-docstring-type-policy.md)) |
| f-strings for formatting | Consistency and readability |
| `const()` / `memoryview` in library code | Memory efficiency on microcontrollers (not required in `scripts/` or `support/`) |

## Getting help

- **Something broken?** Open a [bug report](https://github.com/ChuMicro/ChuMicro/issues/new?template=bug_report.yml)
- **Have an idea?** Open a [feature request](https://github.com/ChuMicro/ChuMicro/issues/new?template=feature_request.yml)
- **Using an agent?** See [`AGENTS.md`](AGENTS.md) for the complete rule set
- **Questions about decisions?** Browse [`plans/decisions/`](plans/decisions/) — they explain *why* things work the way they do

## License

By contributing, you agree that your contributions will be licensed under the [MIT License](LICENSE).

