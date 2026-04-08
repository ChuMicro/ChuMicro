# Creating a Pull Request

Step-by-step guide to contributing a change — from fork to merged PR. Every step shows the commands and expected output.

## 1. Fork and clone

Fork the repo on GitHub, then clone your fork:

```bash
git clone https://github.com/<your-username>/ChuMicro.git
cd ChuMicro
```

Add the upstream remote so you can pull future changes:

```bash
git remote add upstream https://github.com/ChuMicro/ChuMicro.git
```

## 2. Set up the environment

```bash
python scripts/prepare_workspace.py --create-venv
```

Expected output (last few lines):

```
✓ Dependencies installed
✓ Lint passed
✓ Tests passed
Workspace is ready.
```

For IDE-specific setup, see the [PyCharm](development-pycharm.md) or [VS Code](development-vscode.md) development guides.

## 3. Create a branch

```bash
git checkout main
git pull upstream main
git checkout -b fix/my-first-change
```

Use the [branching conventions](../CONTRIBUTING.md#branching-conventions):
- `fix/` for bug fixes
- `feature/` for new features
- `docs/` for documentation changes

## 4. Make your change

Pick something small for your first PR. Good first contributions:

- Fix a typo in docs or docstrings
- Add a missing test case
- Improve an example
- Add a missing docstring

### Example: adding a test

Say you want to add a test to the `timing` library. Create or edit a file in `libraries/timing/tests/`:

```python
"""Tests for ticks_add edge cases."""

from chumicro_timing import ticks_add


def test_ticks_add_zero():
    """Adding zero returns the original value."""
    assert ticks_add(1000, 0) == 1000
```

## 5. Run checks

Run the checks that CI will run. Start narrow and expand:

```bash
# Test just the library you changed
python scripts/run.py test --libraries timing
```

Expected output (last few lines):

```
---------- coverage: ... ----------
Name                              Stmts   Miss Branch BrPart  Cover
...
TOTAL                               ...    ...    ...    ...    95%

Required coverage of 94% reached. ✓
```

```bash
# Lint
python scripts/run.py lint
```

Expected:

```
All checks passed!
```

```bash
# Full preflight (runs everything CI runs)
python scripts/run.py preflight 2>&1 | tail -5
```

Expected:

```
Preflight passed — required CI checks should pass.
```

For IDE-specific ways to run these checks, see the [PyCharm](development-pycharm.md) or [VS Code](development-vscode.md) guides. For detailed output examples (including failures), see the [CLI guide](development-cli.md#validation-checklist).

## 6. Commit

Never use `git commit -m`. Write the message to `.scratch/commit-msg.txt` with your editor:

```bash
nano .scratch/commit-msg.txt
```

Example message:

```
Add edge-case test for ticks_add with zero delta

Verifies that ticks_add(x, 0) returns x unchanged.

Affects: timing
```

Then commit:

```bash
git add -A
git commit -F .scratch/commit-msg.txt
```

Verify:

```bash
git log --oneline -1
```

Expected:

```
a1b2c3d Add edge-case test for ticks_add with zero delta
```

## 7. Push

```bash
git push -u origin fix/my-first-change
```

## 8. Open the PR

**Option A — GitHub UI:**

Go to your fork on GitHub. You'll see a banner: "fix/my-first-change had recent pushes — Compare & pull request." Click it.

**Option B — GitHub CLI:**

```bash
gh pr create --title "Add edge-case test for ticks_add" --body "See commit message" --base main
```

Fill in the PR template:

- **Summary:** What your PR does (one sentence)
- **Motivation:** Why this change is needed
- **Changes:** List the files changed
- **How to verify:** Concrete steps (`python scripts/run.py test --libraries timing`)
- **Device testing:** Screenshot/video + console output from a real device (see below)
- **Version impact:** For test-only changes, select "No bump needed"

## 9. Device testing

For library code changes, your PR must include evidence of on-device testing:

1. **Screenshot or video** of the code running on a device
2. **Console output** (scrub any PII — WiFi credentials, IP addresses, etc.)
3. **Board used** (e.g., "Adafruit QT Py ESP32-S3")
4. **Runtime and version** (e.g., "CircuitPython 10.1.4" or "MicroPython v1.26.0")
5. **What manual tests were run** and their results

Drag images/videos directly into the PR description on GitHub — they upload automatically.

**Exceptions** (note the reason in the PR and delete the Device Testing section):

- Docs-only, test-only, or infrastructure-only changes
- Trivial fixes (typos, comment corrections)
- Changes to `support/` or `scripts/` (CPython-only code)
- Libraries with no hardware interaction (e.g., `compat`, `msgpack`)

**Don't have a device?** Say so in the PR — a maintainer can help test.

## 10. CI runs

After you open the PR, GitHub Actions runs the full CI suite:

```
✓ lint
✓ test (3.11, 3.12, 3.13)
✓ verify-examples
✓ documentation-build
✓ build
✓ version-check
✓ api-check
✓ MicroPython compatibility
✓ CircuitPython compatibility
```

All checks must pass before merge. If something fails:

1. Click the failed check to see the log
2. Fix the issue locally
3. Push again — CI re-runs automatically

Common failures:

| Check | Typical cause | Fix |
|---|---|---|
| `test` | Coverage below 94% | Add more tests |
| `lint` | Formatting issue | Run `python scripts/run.py lint` locally and fix |
| `version-check` | Changed source without bumping VERSION | Edit `libraries/<name>/VERSION` |
| `api-check` | Removed or renamed a public function | Bump VERSION to next minor/major |

## 11. Review and merge

A maintainer will review your PR. They may:

- Approve and merge
- Request changes (you'll get a notification)
- Leave comments for discussion

After merge, your change is on `main`. If you bumped a VERSION file, an experimental release publishes automatically.

## Keeping your fork up to date

Before starting new work:

```bash
git checkout main
git pull upstream main
git push origin main
```

## Quick reference

| Step | Command |
|------|---------|
| Create branch | `git checkout -b fix/description` |
| Run tests | `python scripts/run.py test --libraries <name>` |
| Run lint | `python scripts/run.py lint` |
| Full check | `python scripts/run.py preflight 2>&1 \| tail -5` |
| Commit | `git add -A && git commit -F .scratch/commit-msg.txt` |
| Push | `git push -u origin <branch>` |
| Open PR | `gh pr create` or GitHub UI |

