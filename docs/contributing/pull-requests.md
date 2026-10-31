# Creating a Pull Request

<img src="https://chumicro.com/assets/chumicro-head.png" alt="" align="left" width="64" style="margin-right: 16px; margin-bottom: 8px;">

This guide picks up once you have changes ready to submit. For environment setup, see [Setting up](https://github.com/ChuMicro/ChuMicro/blob/main/CONTRIBUTING.md#setting-up) in the contributing guide.

<br clear="left">

## Before you start

Make sure you've:

1. Forked and cloned the repository
2. Set up your development environment (see [Setting up](https://github.com/ChuMicro/ChuMicro/blob/main/CONTRIBUTING.md#setting-up))
3. Created a branch (see [Your first change](https://github.com/ChuMicro/ChuMicro/blob/main/CONTRIBUTING.md#your-first-change-a-worked-example), which walks the branch-off-main steps)
4. Made your changes and run preflight

> **Trivial docs fix?** GitHub's web editor (the pencil icon on any file) plus the PR template is a fine path for typos, broken links, and one-line clarifications. You skip local setup entirely, and CI runs preflight on the PR for you. Use the full local workflow for anything bigger.

Preflight runs every check CI runs on a pull request, in one command:

```bash
python scripts/run.py preflight
```

A green run ends with a line that starts:

```
Preflight passed.  Required CI checks should pass.
```

## Commit your changes

Stage the files you changed by name, then commit. Git opens your default editor for the message:

```bash
git add <changed files>
git commit
```

Name each path rather than running `git add -A`, so unrelated changes lying around in your tree stay out of the commit.

Write a message like:

```
Add an edge-case test for ticks_add with a zero delta

ticks_add(x, 0) must return x unchanged at every point on the tick
ring, including right at the wrap.  Nothing tested the wrap point.
```

Use imperative mood in the subject: "Add test", not "Added" or "Adds". Explain *why* in the body; the diff already shows what.

> **Working with an AI agent?** Many agent tools append a `Co-Authored-By:` trailer to every commit.  Delete it before committing: commits in this repo are authored by the person running the agent.  [`AGENTS.md`](https://github.com/ChuMicro/ChuMicro/blob/main/AGENTS.md) § Git carries the full commit rules agents follow here.

## Push and open the PR

```bash
git push -u origin fix/my-first-change
```

Go to your fork on GitHub (`github.com/<your-username>/ChuMicro`). You'll see a banner noting that `fix/my-first-change` had recent pushes, with a "Compare & pull request" button. Click it.

GitHub knows your fork came from the original repository, so it sets up the PR to merge your branch into `ChuMicro/ChuMicro`'s `main`. Check that the header reads **base repository: ChuMicro/ChuMicro** and **base: main**.  If it points at your own fork instead, change the base repository dropdown.

PRs land as a single squashed commit, and the PR title becomes that commit's subject on `main`.  Give the title the same imperative, one-line care as a commit subject.

GitHub loads the PR template automatically. Fill in each section:

- **Summary:** what your PR does and why, in one or two sentences
- **Changes:** the key changes, grouped by library when several are affected
- **How to verify:** concrete steps a reviewer can run (`pytest libraries/timing/tests/`)
- **Device testing:** the PR-summary block from a board run, or N/A (see [below](#device-testing))
- **Version impact:** the bump type and affected libraries, or N/A (see [VERSION bumps](https://github.com/ChuMicro/ChuMicro/blob/main/CONTRIBUTING.md#version-bumps))
- **Breaking changes:** any removed or renamed public API, or None

<details>
<summary>Example: a filled-in PR</summary>

```markdown
## Summary

Fix the wraparound bug in ticks_diff when end is near zero and start is near the top of the ring.

## Changes

- `libraries/timing/src/chumicro_timing/ticks.py`: fix the boundary comparison in `ticks_diff`
- `libraries/timing/tests/test_ticks.py`: add wraparound boundary tests
- `libraries/timing/VERSION`: patch bump, 0.8.4 to 0.8.5

## How to verify

Run `pytest libraries/timing/tests/`.  New tests in `test_ticks.py` cover the boundary case.

## Device testing

N/A, pure arithmetic fix with full test coverage.

## Version impact

Patch bump: timing 0.8.4 to 0.8.5

## Breaking changes

None
```

</details>

> **Prefer the GitHub UI.**  It loads the PR template automatically. From the command line, `gh pr create --template .github/PULL_REQUEST_TEMPLATE.md` does the same.

## Device testing

CI runs every library's unit tests under the unix ports, the desktop builds of CircuitPython and MicroPython, which catches most cross-runtime problems. Device testing is **optional**.  It adds confidence and is never required to open a PR.

### When device testing helps

If your change could behave differently on a real board than in tests (timing-sensitive code, runtime-specific branches, hardware I/O), board evidence is welcome. If you're not sure, submit the PR without it and say so in the description. A reviewer will tell you if it's needed.

These changes never need it:

- **Docs-only, test-only, or tooling-only** changes
- **Trivial fixes** (typos, comment corrections, formatting)
- **Libraries with no hardware interaction** (`compat`, `msgpack`)

### What to include

Run the library's functional tests on your board:

```bash
python scripts/run.py test-libraries-functional --library timing
python scripts/run.py test-libraries-functional --runtime both --library timing
```

The run ends by printing a Markdown "PR summary" block with the exact command, each board's id, runtime, and address, and the pass and fail counts.  Paste that block into the **Device testing** section.  If you tested by running an example instead, paste the console output with the board name (for example "Adafruit QT Py ESP32-S3") and the runtime version ("CircuitPython 10.2.0").  Scrub wifi passwords and IP addresses first.

[Device Testing](device-testing.md) covers registering a board and the rest of the flags.

### Don't have a device?

Say so in the PR. A maintainer can test on the boards they have.  Your PR still goes through; the merge may wait a little longer while someone verifies on a board.

## CI checks

After you open the PR, GitHub Actions runs three required checks.  On your first contribution, GitHub waits for a maintainer to approve the run before anything starts, so "waiting for approval" on a fresh PR is normal.

| Check | What it runs | Reproduce locally |
|---|---|---|
| `preflight` | The same 13 phases as `python scripts/run.py preflight` | `python scripts/run.py preflight` |
| `compatibility (3.11)`, `(3.12)`, `(3.13)` | The unit tests under each older Python | `python scripts/run.py test --all` from a venv on that Python version |
| `Validate mpy bytecode` | Compiles every library to `.mpy`, then checks MicroPython can `mip`-install and import it | See below |

If a check fails:

1. Click the failed check to see the log
2. Fix the issue locally
3. Push again, and CI re-runs automatically

[The development loop](https://github.com/ChuMicro/ChuMicro/blob/main/CONTRIBUTING.md#the-development-loop) in the contributing guide covers how to read each preflight phase's failure (coverage gaps, lint, docstring warnings, a missing VERSION bump, cross-runtime breaks).

When `Validate mpy bytecode` fails, its log names the library that would not install or import.  To reproduce for one library (here `timing`), after `python scripts/run.py prepare-micropython` and `python scripts/run.py prepare-mpy-cross`:

```bash
python scripts/bundle_manager.py stage libraries/timing "$(cat libraries/timing/VERSION)" .scratch/bundle-staging
python scripts/run.py validate-mip --staging-dir .scratch/bundle-staging --libraries timing
```

## Review and merge

A maintainer reviews your PR. They may:

- Approve and merge
- Request changes (you'll get a notification)
- Leave comments for discussion
- Comment `@claude /review`, which has Claude post a first review pass

AI review comments are advisory. The maintainer decides what matters, and you can push back on a finding you disagree with, exactly as with a human reviewer. Only maintainers can trigger the command, so a PR gets an AI review only when a person asked for one.

After the merge, your change is on `main`. If you bumped a `VERSION` file, an experimental release publishes automatically. See [Releases and Promotion](releases.md) for how that works.

## Keeping your fork up to date

Your fork doesn't update on its own. Before starting new work, sync it with the original repository:

```bash
git checkout main
git pull upstream main
git push origin main
git checkout -b fix/next-change
```

If `main` moves while your PR is open, the closing steps of [Your first change](https://github.com/ChuMicro/ChuMicro/blob/main/CONTRIBUTING.md#your-first-change-a-worked-example) show how to rebase your branch onto it.

## Quick reference

| Step | Command |
|------|---------|
| Create branch | `git checkout -b fix/description` |
| Run tests | `pytest libraries/<name>/tests/` |
| Run lint | `python scripts/run.py lint` |
| Full check | `python scripts/run.py preflight` |
| Commit | `git add <changed files> && git commit` |
| Push | `git push -u origin <branch>` |
| Open PR | GitHub UI: click "Compare & pull request" on your fork |
