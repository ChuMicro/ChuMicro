# Creating a Pull Request

This guide covers what happens once you have changes ready to submit. For environment setup and running tasks, see [CONTRIBUTING.md](../../CONTRIBUTING.md) and your [development environment guide](../../CONTRIBUTING.md#development-environment).

## Before you start

Make sure you've:

1. Forked and cloned the repository
2. Set up your development environment (see [Quick start](../../CONTRIBUTING.md#quick-start))
3. Created a branch (see [Branching conventions](../../CONTRIBUTING.md#branching-conventions))
4. Made your changes and validated them

> **Trivial docs fix?** GitHub's web editor (the pencil icon on any file) + the PR template is a legitimate path for typos, broken links, and one-line clarifications. You skip the local setup entirely; CI still runs the checks. Save the full local workflow for changes that need preflight.

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
- **Changes:** List the files changed
- **How to verify:** Concrete steps (`python scripts/run.py test --libraries timing`)
- **Device testing:** Evidence of on-device testing, or N/A (see [below](#device-testing))
- **Version impact:** Bump type and affected libraries, or N/A for test/docs/infra changes
- **Breaking changes:** Describe any removed or renamed public API, or None

<details>
<summary>Example: a filled-in PR</summary>

```markdown
## Summary

Fix wraparound bug in ticks_diff when end is near zero and start is near max.

## Changes

- `libraries/timing/src/chumicro_timing/ticks.py` — fix boundary comparison in `ticks_diff`
- `libraries/timing/tests/test_ticks.py` — add wraparound boundary tests
- `libraries/timing/VERSION` — patch bump 0.1.15 → 0.1.16

## How to verify

Run `python scripts/run.py test --libraries timing` — new tests in `test_ticks.py` cover the boundary case.

## Device testing

N/A — pure arithmetic fix with full test coverage.

## Version impact

Patch bump: timing 0.1.15 → 0.1.16

## Breaking changes

None
```

</details>

> **Prefer the GitHub UI** — it loads the PR template automatically so reviewers get the context they need. If you prefer the CLI, use `gh pr create --template .github/PULL_REQUEST_TEMPLATE.md` to include the template.

## Device testing

CI runs your code under unix-port builds of CircuitPython and MicroPython, which catches most cross-runtime issues. Device testing is **optional** — it provides extra confidence but is never required to open a PR.

### When device testing helps

If your change could behave differently on a real board than in tests — timing-sensitive code, platform-specific branches, hardware I/O — device testing evidence is appreciated. If you're not sure, submit the PR without it and note that in the description. A reviewer will tell you if it's needed.

### What doesn't need device testing

- **Docs-only, test-only, or infrastructure-only** changes
- **Trivial fixes** (typos, comment corrections, formatting)
- **Libraries with no hardware interaction** (e.g., `compat`, `msgpack`)

### What to include (when you do test)

1. **Console output** from running the library on a device (scrub any PII — WiFi passwords, IP addresses)
2. **Board name** (e.g., "Adafruit QT Py ESP32-S3")
3. **Runtime and version** (e.g., "CircuitPython 10.1.4" or "MicroPython v1.26.0")
4. **What was tested** — which examples or functional tests you ran, and their results

Paste the output directly in the PR description or as a comment.

### Example commands for gathering device-test evidence

If you want a quick way to collect that information, these commands are typical:

```bash
python scripts/run.py test-libraries-functional --library timing
python scripts/run.py test-libraries-functional --runtime both --library timing
```

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
| `test` | Coverage below threshold | Follow the hint below the FAIL line — it points to the uncovered lines |
| `lint` | Formatting issue or banned name/whitespace | Run `python scripts/run.py lint` locally — it runs Ruff plus the workspace's `CHU001` (names) and `CHU002`–`CHU005` (whitespace) checks |
| `version-check` | Changed source without bumping VERSION | Edit `libraries/<name>/VERSION` |
| `api-check` | Removed or renamed a public function | Bump VERSION to next minor/major |
| `validate-mpy` | mpy-cross failed to compile a library, or the staged bundle's `package.json` is broken | Build the bundle locally (`python scripts/run.py build`) and check the validate-mpy job log for the failing library |
| `cross-runtime-tests` (MicroPython / CircuitPython) | Test fails under the unix-port build of one runtime | Reproduce locally with `python scripts/run.py test-micropython` or `test-circuitpython` |

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
