# Creating a Pull Request

This guide covers what happens once you have changes ready to submit. For environment setup and running tasks, see [CONTRIBUTING.md](../../CONTRIBUTING.md) and your [development environment guide](../../CONTRIBUTING.md#development-environment).

## Before you start

Make sure you've:

1. Forked and cloned the repository
2. Set up your development environment (see [Quick start](../../CONTRIBUTING.md#quick-start))
3. Created a branch (see [Branching conventions](../../CONTRIBUTING.md#branching-conventions))
4. Made your changes and validated them

If you haven't validated yet, run preflight:

```bash
python scripts/run.py preflight
```

Expected:

```
Preflight passed — required CI checks should pass.
```

## Commit your changes

Stage and commit. Git opens your default editor for the message:

```bash
git add -A
git commit
```

Write a message like:

```
Add edge-case test for ticks_add with zero delta

Verifies that ticks_add(x, 0) returns x unchanged.

Affects: timing
```

Use imperative mood in the subject — "Add test", not "Added" or "Adds". Name affected libraries in the body.

## Push and open the PR

```bash
git push -u origin fix/my-first-change
```

Go to your fork on GitHub (`github.com/<your-username>/ChuMicro`). You'll see a banner: "fix/my-first-change had recent pushes — Compare & pull request." Click it.

GitHub knows your fork came from the original repository, so it automatically sets up the PR to merge your branch into `ChuMicro/ChuMicro`'s `main`. Verify the header reads **base repository: ChuMicro/ChuMicro** and **base: main** — if it points at your own fork instead, change the base repository dropdown.

GitHub loads the PR template automatically. Fill in each section:

- **Summary:** What your PR does (one sentence)
- **Motivation:** Why this change is needed
- **Changes:** List the files changed
- **How to verify:** Concrete steps (`python scripts/run.py test --libraries timing`)
- **Device testing:** Evidence of on-device testing, if applicable (see below)
- **Version impact:** For test-only changes, select "No bump needed"

> **Prefer the GitHub UI over `gh pr create`.** The UI auto-populates the PR template so reviewers get the context they need. The CLI skips it, which usually means a reviewer has to ask follow-up questions before they can review — slowing things down.

## Device testing

CI runs your code under unix-port builds of CircuitPython and MicroPython, which catches most cross-runtime issues. But some problems only surface on real hardware — memory constraints, timing behavior, peripheral interaction. Device testing provides that final layer of confidence.

### What doesn't need device testing

Most contributions are exempt. Skip this section if your PR is:

- **Docs-only, test-only, or infrastructure-only** (changes to `docs/`, `tests/`, `scripts/`, `support/`)
- **Trivial fixes** (typos, comment corrections, formatting)
- **Libraries with no hardware interaction** (e.g., `compat`, `msgpack`)

Note the exemption in the PR and delete the Device Testing section from the template.

### What does need device testing

PRs that change library source code under `src/` — especially code that interacts with hardware, timing, or I/O — should include evidence that the code works on a real device.

**Borderline cases:** Not every change to `timing` or `runner` needs device testing. A bug fix in `ticks_diff` with full test coverage: device testing appreciated but not required. A change to tick-source detection logic or platform-specific code paths: device testing strongly recommended. Use judgment — if your change could behave differently on real hardware than in tests, device testing adds confidence.

**What to include:**

1. **Console output** from running the library on a device (scrub any PII — WiFi passwords, IP addresses)
2. **Board name** (e.g., "Adafruit QT Py ESP32-S3")
3. **Runtime and version** (e.g., "CircuitPython 10.1.4" or "MicroPython v1.26.0")
4. **What was tested** — which examples or functional tests you ran, and their results

Screenshots or short videos of the device in action are welcome but not required — console output showing the code executing successfully is the primary evidence.

Paste the output directly in the PR description or as a comment. Drag images/videos into the PR on GitHub — they upload automatically.

### Don't have a device?

Say so in the PR. A maintainer can help test on available hardware. This won't block your contribution — it just means the merge may take a bit longer while someone verifies on-device.

## CI checks

After you open the PR, GitHub Actions runs the full CI suite. If something fails:

1. Click the failed check to see the log
2. Fix the issue locally
3. Push again — CI re-runs automatically

Common failures:

| Check | Typical cause | Fix |
|---|---|---|
| `test` | Coverage below 94% | Follow the hint below the FAIL line — it points to the uncovered lines |
| `lint` | Formatting issue | Run `python scripts/run.py lint` locally and fix |
| `version-check` | Changed source without bumping VERSION | Edit `libraries/<name>/VERSION` |
| `api-check` | Removed or renamed a public function | Bump VERSION to next minor/major |

For detailed output examples (success and failure), see your [development environment guide](../../CONTRIBUTING.md#development-environment).

## Review and merge

A maintainer will review your PR. They may:

- Approve and merge
- Request changes (you'll get a notification)
- Leave comments for discussion

After merge, your change is on `main`. If you bumped a VERSION file, an experimental release publishes automatically. See [Releases and Promotion](releases.md) for how that works.

## Keeping your fork up to date

Your fork doesn't update automatically. Before starting new work, sync it with the original repository. See [Keeping your fork in sync](../../CONTRIBUTING.md#keeping-your-fork-in-sync) in the contributing guide for full instructions, including how to rebase your branch if `main` moves while you're working.

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
| Run tests | `python scripts/run.py test --libraries <name>` |
| Run lint | `python scripts/run.py lint` |
| Full check | `python scripts/run.py preflight` |
| Commit | `git add -A && git commit` |
| Push | `git push -u origin <branch>` |
| Open PR | GitHub UI — click "Compare & pull request" on your fork |

