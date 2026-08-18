# Creating a Pull Request

<img src="https://chumicro.com/assets/chumicro-head.png" align="left" width="64" style="margin-right: 16px; margin-bottom: 8px;">

This guide covers what happens once you have changes ready to submit. For environment setup and running tasks, see [CONTRIBUTING.md](https://github.com/ChuMicro/ChuMicro/blob/main/CONTRIBUTING.md) and its [Setting up](https://github.com/ChuMicro/ChuMicro/blob/main/CONTRIBUTING.md#setting-up) section.

<br clear="left">

## Before you start

Make sure you've:

1. Forked and cloned the repository
2. Set up your development environment (see [Setting up](https://github.com/ChuMicro/ChuMicro/blob/main/CONTRIBUTING.md#setting-up))
3. Created a branch (see [Your first change](https://github.com/ChuMicro/ChuMicro/blob/main/CONTRIBUTING.md#your-first-change-a-worked-example), which walks the branch-off-main steps)
4. Made your changes and validated them

> **Trivial docs fix?** GitHub's web editor (the pencil icon on any file) + the PR template is a legitimate path for typos, broken links, and one-line clarifications. You skip the local setup entirely; CI still runs the checks. Save the full local workflow for changes that need preflight.

If you haven't validated yet, run preflight:

```bash
python scripts/run.py preflight
```

Expected:

```
Preflight passed.  Required CI checks should pass.
```

## Commit your changes

Stage the files you changed, then commit. Git opens your default editor for the message:

```bash
git add <changed files>
git commit
```

Stage explicit paths rather than `git add -A`, so unrelated changes lying around in your tree don't ride along into the commit.

Write a message like:

```
Add edge-case test for ticks_add with zero delta

Verifies that ticks_add(x, 0) returns x unchanged.

Affects: timing
```

Use imperative mood in the subject: "Add test", not "Added" or "Adds". Name affected libraries in the body.

> **Working with an AI agent?** Strip any default agent-authorship trailer (e.g. `Co-Authored-By: Claude …`) before committing.  Commits in this repo are authored by the human running the agent.  See the AGENTS.md non-negotiable rules and the `git-commit` skill.  Most agent harnesses add the trailer automatically; strip it from your commit message before invoking `git commit`.

## Push and open the PR

```bash
git push -u origin fix/my-first-change
```

Go to your fork on GitHub (`github.com/<your-username>/ChuMicro`). You'll see a banner noting that `fix/my-first-change` had recent pushes, with a "Compare & pull request" button. Click it.

GitHub knows your fork came from the original repository, so it automatically sets up the PR to merge your branch into `ChuMicro/ChuMicro`'s `main`. Verify the header reads **base repository: ChuMicro/ChuMicro** and **base: main**.  If it points at your own fork instead, change the base repository dropdown.

GitHub loads the PR template automatically. Fill in each section:

- **Summary:** What your PR does (one sentence)
- **Changes:** List the files changed
- **How to verify:** Concrete steps (`pytest libraries/timing/tests/`)
- **Device testing:** Evidence of on-device testing, or N/A (see [below](#device-testing))
- **Version impact:** Bump type and affected libraries, or N/A for test/docs/infra changes
- **Breaking changes:** Describe any removed or renamed public API, or None

<details>
<summary>Example: a filled-in PR</summary>

```markdown
## Summary

Fix wraparound bug in ticks_diff when end is near zero and start is near max.

## Changes

- `libraries/timing/src/chumicro_timing/ticks.py`: fix boundary comparison in `ticks_diff`
- `libraries/timing/tests/test_ticks.py`: add wraparound boundary tests
- `libraries/timing/VERSION`: patch bump 0.1.15 → 0.1.16

## How to verify

Run `pytest libraries/timing/tests/`.  New tests in `test_ticks.py` cover the boundary case.

## Device testing

N/A, pure arithmetic fix with full test coverage.

## Version impact

Patch bump: timing 0.1.15 → 0.1.16

## Breaking changes

None
```

</details>

> **Prefer the GitHub UI.**  It loads the PR template automatically so reviewers get the context they need. If you prefer the CLI, use `gh pr create --template .github/PULL_REQUEST_TEMPLATE.md` to include the template.

## Device testing

CI runs your code under unix-port builds of CircuitPython and MicroPython, which catches most cross-runtime issues. Device testing is **optional**.  It provides extra confidence but is never required to open a PR.

### When device testing helps

If your change could behave differently on a real board than in tests (timing-sensitive code, platform-specific branches, hardware I/O), device testing evidence is appreciated. If you're not sure, submit the PR without it and note that in the description. A reviewer will tell you if it's needed.

### What doesn't need device testing

- **Docs-only, test-only, or infrastructure-only** changes
- **Trivial fixes** (typos, comment corrections, formatting)
- **Libraries with no hardware interaction** (e.g., `compat`, `msgpack`)

### What to include (when you do test)

1. **Console output** from running the library on a device (scrub any PII: WiFi passwords, IP addresses)
2. **Board name** (e.g., "Adafruit QT Py ESP32-S3")
3. **Runtime and version** (e.g., "CircuitPython 10.2.0" or "MicroPython v1.26.0")
4. **What was tested:** which examples or functional tests you ran, and their results

Paste the output directly in the PR description or as a comment.

### Example commands for gathering device-test evidence

If you want a quick way to collect that information, these commands are typical:

```bash
python scripts/run.py test-libraries-functional --library timing
python scripts/run.py test-libraries-functional --runtime both --library timing
```

### Don't have a device?

Say so in the PR. A maintainer can help test on available hardware. This won't block your contribution.  It just means the merge may take a bit longer while someone verifies on-device.

## CI checks

After you open the PR, GitHub Actions runs the full CI suite. If this is your first contribution here, GitHub waits for a maintainer to approve the run before anything starts, so "waiting for approval" on a fresh PR is normal and not a problem with your change. If something fails:

1. Click the failed check to see the log
2. Fix the issue locally
3. Push again, and CI re-runs automatically

Each failing check names its cause in the log.  [The development loop](https://github.com/ChuMicro/ChuMicro/blob/main/CONTRIBUTING.md#the-development-loop) in the contributing guide covers how to read the common ones (coverage gaps, lint violations, docstring warnings, a missed VERSION bump, cross-runtime breaks) and how to reproduce each locally.  The CI-only checks are `check-api` (bump VERSION to the next minor or major when you remove or rename a public function) and `validate-mpy` (build the bundle with `python scripts/run.py build` and read the failing library out of the job log).

For detailed output examples (success and failure), see your [development environment guide](https://github.com/ChuMicro/ChuMicro/blob/main/CONTRIBUTING.md#setting-up).

## Review and merge

A maintainer will review your PR. They may:

- Approve and merge
- Request changes (you'll get a notification)
- Leave comments for discussion
- Comment `@claude /review`, which has Claude post a first review pass

AI review comments are advisory. The maintainer decides what matters, and pushing back on a finding you disagree with is fine, exactly as with a human reviewer. The command only works for maintainers, so a PR is never reviewed by AI unless a human asked for it.

After merge, your change is on `main`. If you bumped a VERSION file, an experimental release publishes automatically. See [Releases and Promotion](releases.md) for how that works.

## Keeping your fork up to date

Your fork doesn't update automatically. Before starting new work, sync it with the original repository. The closing steps of [Your first change](https://github.com/ChuMicro/ChuMicro/blob/main/CONTRIBUTING.md#your-first-change-a-worked-example) in the contributing guide cover keeping your fork in sync, including how to rebase your branch if `main` moves while you're working.

The short version:

```bash
git checkout main
git pull upstream main
git push origin main
git checkout -b fix/next-change
```

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
