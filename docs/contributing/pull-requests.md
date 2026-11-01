# Creating a Pull Request

<img src="https://chumicro.com/assets/chumicro-head.png" alt="" align="left" width="64" style="margin-right: 16px; margin-bottom: 8px;">

A pull request starts from a branch whose preflight passes. [CONTRIBUTING § Your first change](https://github.com/ChuMicro/ChuMicro/blob/main/CONTRIBUTING.md#your-first-change-a-worked-example) walks branching, testing, and committing, and [Commit messages](https://github.com/ChuMicro/ChuMicro/blob/main/CONTRIBUTING.md#commit-messages) sets the commit rules.

<br clear="left">

## Push and open the pull request

```bash
git push -u origin fix/my-first-change
```

Your fork's page on GitHub, `github.com/<your-username>/ChuMicro`, shows a banner for the branch you just pushed, with a **Compare & pull request** button. Click it.

GitHub sets up the pull request to merge your branch into `ChuMicro/ChuMicro`'s `main`. Check that the header reads **base repository: ChuMicro/ChuMicro** and **base: main**. When it names your own fork, change the base repository dropdown.

Title the pull request like a commit subject, as [Commit messages](https://github.com/ChuMicro/ChuMicro/blob/main/CONTRIBUTING.md#commit-messages) describes. GitHub loads the pull request template into the description. Fill in each section:

- **Summary:** what your pull request does and why, in one or two sentences
- **Changes:** the key changes, grouped by library when several are affected
- **How to verify:** concrete steps a reviewer can run, such as `pytest libraries/timing/tests/`
- **Device testing:** the PR-summary block from a board run, or N/A, as [Device testing](#device-testing) describes
- **Version impact:** the bump type and affected libraries, or N/A, following [When to bump VERSION](releases.md#when-to-bump-version)
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

From the command line, `gh pr create --template .github/PULL_REQUEST_TEMPLATE.md` loads the same template.

## Device testing

Board evidence is optional, and a pull request opens without it. CI runs every library's unit tests under the unix ports, the desktop builds of CircuitPython and MicroPython, which catch most cross-runtime problems.

### When device testing helps

Board evidence helps a change that could behave differently on a real board than in tests: timing-sensitive code, runtime-specific branches, hardware I/O. When unsure, open the pull request without it and say so in the description. A reviewer asks for it when it matters.

These changes never need it:

- **Docs-only, test-only, or tooling-only** changes
- **Trivial fixes**, such as typos, comment corrections, or formatting
- **Libraries with no hardware interaction**, such as `compat` and `msgpack`

### What to include

Run the library's functional tests on your board:

```bash
python scripts/run.py test-libraries-functional --library timing
python scripts/run.py test-libraries-functional --runtime both --library timing
```

The run ends by printing a Markdown "PR summary" block with the exact command, each board's id, runtime, and address, and the pass and fail counts. Paste that block into the **Device testing** section. For a test run through an example instead, paste the console output with the board name, for example "Adafruit QT Py ESP32-S3", and the runtime version, such as "CircuitPython 10.2.0". Scrub wifi passwords and IP addresses first.

[Device Testing](device-testing.md) covers registering a board and the rest of the flags.

### Without a board

Say so in the pull request, and a maintainer tests on the boards at hand. The merge may then wait while someone runs it on a board.

## CI checks

GitHub Actions runs these required checks on every pull request. On a first contribution, GitHub waits for a maintainer to approve the run before anything starts, so a fresh pull request can sit at "waiting for approval".

| Check | What it runs | Reproduce locally |
|---|---|---|
| `preflight` | The same 13 phases as `python scripts/run.py preflight` | `python scripts/run.py preflight` |
| `compatibility (3.11)`, `(3.12)`, `(3.13)` | The unit tests under each older Python | `python scripts/run.py test --all` from a venv on that Python version |
| `Validate mpy bytecode` | Compiles every library to `.mpy`, then checks MicroPython can `mip`-install and import it | See below |

When a check fails, click it to read the log, fix the problem locally, and push again. CI re-runs automatically. [CONTRIBUTING § Reading a failure](https://github.com/ChuMicro/ChuMicro/blob/main/CONTRIBUTING.md#reading-a-failure) covers each preflight phase's failures.

When `Validate mpy bytecode` fails, its log names the library that failed to install or import. To reproduce it for `timing`, build the binaries once with `python scripts/run.py prepare-micropython` and `python scripts/run.py prepare-mpy-cross`, then run:

```bash
python scripts/bundle_manager.py stage libraries/timing "$(cat libraries/timing/VERSION)" .scratch/bundle-staging
python scripts/run.py validate-mip --staging-dir .scratch/bundle-staging --libraries timing
```

## Review and merge

The maintainer, [@ChuxMaker](https://github.com/ChuxMaker), reviews and merges every pull request. ChuMicro has one maintainer, so allow a few days for a review. A polite follow-up after a week of silence is welcome.

A review can approve and merge, request changes, or leave comments for discussion. Expect comments even on a green pull request: CI checks that the code works, and review judges naming, scope, and API shape. Push fixes to the same branch, and the pull request updates.

The maintainer can also comment `@claude /review` to have Claude post a first review pass. Its comments are advisory: the maintainer decides what matters, and you can push back on a finding as with any reviewer. Only maintainers can trigger the command, so a pull request gets an AI review only when a maintainer asks for one.

After the merge, your change is on `main`. A merged `VERSION` bump publishes an experimental release, as [Releases and Promotion § What happens on merge](releases.md#what-happens-on-merge) describes. A change without a bump ships with the library's next release.

## Keeping your fork up to date

Sync your fork with the original repository before starting new work:

```bash
git checkout main
git pull upstream main
git push origin main
git checkout -b fix/next-change
```

When `main` moves while your pull request is open, and the branch needs its commits or shows a merge conflict, rebase the branch onto it:

```bash
git checkout main
git pull upstream main
git checkout fix/my-first-change
git rebase main
git push --force-with-lease
```

Rebase instead of merging `main` into the branch. The project keeps its history linear.
