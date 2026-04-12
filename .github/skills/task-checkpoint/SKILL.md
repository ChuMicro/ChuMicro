---
name: task-checkpoint
description: Quick sanity check after completing a unit of work. Use this skill after making file changes, before yielding to the user.
---

# Task Checkpoint

Run this lightweight check after completing each task — before telling the user you're done.

## 1. Review what changed

```bash
git status --short
git diff --stat
```

Scan the output. Ask yourself:
- Are there files I changed that I forgot about?
- Are there files I didn't mean to change?
- Did I leave any temporary or scratch files outside `.scratch/`?

## 2. Run preflight

```bash
python scripts/run.py preflight 2>&1 | tail -5
```

Must show: `Preflight passed`. If it fails because of your work, fix it before committing. Use the `debug-test-failure` skill if tests fail.

## 3. Commit and push if the work is meaningful

If the changes form a coherent unit, commit and push them. Use the `git-commit` skill, then `git push`.

A coherent unit = one logical change that could be described in a single commit message subject line. Examples:
- "Add FakeBackend to settings testing module"
- "Move end-of-session and guide-generation to skills"
- "Fix coverage gap in ticks_diff edge case"

If the work is partial and not yet meaningful, it's fine to leave it uncommitted — but say so.

## 4. Note anything unfinished

If you couldn't complete something, or noticed something that needs follow-up, say it explicitly. Don't let it get lost.

## Rules

- **This is fast.** Preflight takes a few seconds. Steps 1–3 should take under a minute total.
- **Don't skip step 1.** A `git status` catches surprises — files you forgot, files you didn't mean to change, merge artifacts.
- **Don't skip step 2.** Preflight is the single gate. If it passes, CI will pass. Narrow checks miss cross-cutting breakage.
- **Commit and push early.** Small commits are easier to review and revert than large ones. If you've done something useful, commit and push it.

