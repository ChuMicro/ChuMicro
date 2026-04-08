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

## 2. Check for breakage

Run the **narrowest check** that covers your changes:

| What changed | What to run |
|---|---|
| One library's code or tests | `python scripts/run.py test --libraries <name> 2>&1 \| tail -10` |
| Multiple libraries | `python scripts/run.py test --all --no-cov 2>&1 \| tail -5` |
| Scripts or infrastructure | `python scripts/run.py lint 2>&1 \| tail -3` |
| Docs or mkdocs.yml | `python scripts/run.py docs --libraries <name> 2>&1 \| tail -5` |
| Examples | `python scripts/run.py verify-examples --libraries <name>` |
| Not sure / broad changes | `python scripts/run.py lint 2>&1 \| tail -3` then `python scripts/run.py test --all --no-cov 2>&1 \| tail -5` |

Don't run full preflight here — save that for end-of-session.

## 3. Commit if the work is meaningful

If the changes form a coherent unit, commit them. Use the `git-commit` skill.

A coherent unit = one logical change that could be described in a single commit message subject line. Examples:
- "Add FakeBackend to settings testing module"
- "Move end-of-session and guide-generation to skills"
- "Fix coverage gap in ticks_diff edge case"

If the work is partial and not yet meaningful, it's fine to leave it uncommitted — but say so.

## 4. Note anything unfinished

If you couldn't complete something, or noticed something that needs follow-up, say it explicitly. Don't let it get lost.

## Rules

- **This is fast.** Steps 1-3 should take under 30 seconds. If it's taking longer, you're running too broad a check.
- **Don't skip step 1.** A `git status` catches surprises — files you forgot, files you didn't mean to change, merge artifacts.
- **Commit early.** Small commits are easier to review and revert than large ones. If you've done something useful, commit it.
- **Don't run preflight.** That's for `end-of-session`. Here you just want to catch obvious breakage.

