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
python scripts/run.py preflight --coverage-threshold 94 2>&1 | tail -5
```

Must show: `Preflight passed`. If it fails because of your work, fix it before committing. Use the `debug-test-failure` skill if tests fail.

## 3. Compress durable lessons before committing

This is the compression tier — without it, lessons get sealed into dated history entries or commit messages and stop being re-readable.

Ask: **did this session produce something that future sessions need to know without scrolling git log?** Walk the four homes and lift if any apply. Lift *now*, in the same commit as the work, so the dated entry (if any) can be terse.

| Home | Lift when the session produced… | Where it lives |
|------|--------------------------------|----------------|
| `plans/decisions/NNNN-*.md` | A tradeoff or structural choice future contributors will need to know *why* about | New ADR via the `new-decision` skill |
| `plans/patterns.md` | Reusable code shape, subprocess invocation, IDE wiring, transport contract — *how* to implement correctly | Append a section under the right heading |
| `plans/learnings.md` | A non-obvious constraint discovered the hard way: hardware quirk, third-party-tool gotcha, classifier ordering, runtime-specific behavior. Not a rule, not a pattern — a *fact about the world* | Append under the right category |
| `plans/history.md` §`Design principles` / §`Rejected approaches` | A general principle that surfaced from this work, or an approach that was tried and rejected and would otherwise be re-tried | Append a numbered bullet at the top of the right section |
| `AGENTS.md` non-negotiables | An agent-facing rule whose violation already cost time | Append to the rules list |

If nothing lifts, fine — many sessions are routine. But **default to lifting one bullet** rather than zero; the bar is "would I want to know this if I picked up cold", not "is this a flagship insight". A 2-line learnings entry today is worth a 30-minute commit-archaeology session later.

When you do lift, the dated history entry — if you write one — should shrink to a 1-2 line pointer naming the commit range and the lifted artifacts:

```markdown
### 2026-MM-DD — <topic>
<one-sentence summary>. Commits `<short>..<short>`. Lifted: <Decision NNNN>, <Pattern X>, <Learning Y>.
```

The detailed prose lives in those artifacts now. `git log <range>` rebuilds the rest.

**When NOT to add a dated history entry at all:** if the session is fully captured by its commit messages plus any artifacts you lifted, skip the dated entry. `history.md` is the synthesized layer, not a journal of record — that's what `git log` is for.

## 4. Refresh `plans/now.md`

Overwrite `plans/now.md` with the current 30-second brain snapshot. Five lines:

- **Phase:** what workstream / milestone is active
- **Last shipped:** subject line of the most recent commit that closed something
- **In flight:** the one thing currently in progress (or "idle" if none)
- **Blocked on:** anything waiting on user / hardware / external (or "—")
- **Last touched:** decisions / workstreams / open-questions edited this session

This is the front door for the next session's context recovery. It replaces the first 60 seconds of "what was I doing".

## 5. Commit and push if the work is meaningful

If the changes form a coherent unit, commit and push them. Use the `git-commit` skill, then `git push`.

A coherent unit = one logical change that could be described in a single commit message subject line. The compression artifacts from step 3 and the `plans/now.md` refresh from step 4 ride along in the same commit — they are part of the unit of work, not a separate housekeeping commit.

If the work is partial and not yet meaningful, it's fine to leave it uncommitted — but say so.

## 6. Note anything unfinished

If you couldn't complete something, or noticed something that needs follow-up, say it explicitly. Don't let it get lost.

## Rules

- **This is fast.** Preflight takes a few seconds. Step 3 takes under a minute on the average session and is skipped entirely on routine ones. The whole checkpoint should fit inside two minutes.
- **Don't skip step 1.** A `git status` catches surprises — files you forgot, files you didn't mean to change, merge artifacts.
- **Don't skip step 2.** Preflight is the single gate. If it passes, CI will pass. Narrow checks miss cross-cutting breakage.
- **Step 3 is the compression tier.** `plans/history.md` is *synthesized* knowledge, not a journal — `git log` is the journal. If you find yourself writing a long dated entry, stop and ask whether the prose should be a Pattern, a Learning, a Decision, or a Principle instead.
- **Step 4 is cheap.** `plans/now.md` is five lines. Always update it. The next session will thank you.
- **Commit and push early.** Small commits are easier to review and revert than large ones. The compression artifacts ride with the work — one commit, not two.
