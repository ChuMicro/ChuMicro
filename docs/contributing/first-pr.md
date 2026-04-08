# Your First Pull Request

This guide walks you through making your first contribution — from fork to merged PR. Every step shows the commands and what to expect.

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

**PyCharm users:** Open the project folder. Shared run configurations appear automatically — look for Preflight, Lint, Test, Build in the run dropdown.

**VS Code users:** Open the folder. Tasks are available via Command Palette → *Tasks: Run Task*.

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

Expected: no output (clean lint = silence).

```bash
# Full preflight (runs everything CI runs)
python scripts/run.py preflight 2>&1 | tail -5
```

Expected:

```
Preflight passed — required CI checks should pass.
```

**PyCharm:** click the ▶ button next to "Preflight" in the run dropdown.

**VS Code:** Command Palette → *Tasks: Run Task* → Preflight.

## 6. Commit

Never use `git commit -m`. Write the message to a file:

```bash
cat > .scratch/commit-msg.txt << 'EOF'
Add edge-case test for ticks_add with zero delta

Verifies that ticks_add(x, 0) returns x unchanged.

Affects: timing
EOF

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
- **Version impact:** For test-only changes, select "No bump needed"

## 9. CI runs

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

## 10. Review and merge

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

