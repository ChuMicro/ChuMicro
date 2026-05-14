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
| Inline code comment | A non-obvious constraint discovered the hard way (hardware quirk, third-party-tool gotcha, runtime-specific behavior) — anywhere a reader of the code might trip on the same surface | One-line `# `-comment next to the workaround; keep the prose in the commit message |
| `AGENTS.md` non-negotiables | An agent-facing rule whose violation already cost time | Append to the rules list |
| Commit message body | Narrative context, what was tried and rejected, the rationale a future reader will want when running `git log <range>` | The commit you're about to write |

If nothing lifts, fine — many sessions are routine. But **default to lifting one bullet** rather than zero; the bar is "would I want to know this if I picked up cold", not "is this a flagship insight". A 2-line learnings entry today is worth a 30-minute commit-archaeology session later.

`git log` is the journal — there's no separate dated-timeline file. Every session produces commit messages; durable cross-session signal gets lifted into the homes above so future sessions don't need to re-derive it from `git log`.

## 4. Refresh `plans/next-up.md`

`next-up.md` is the agent-managed work queue and the single source of truth for what's in flight, queued, blocked, and recently shipped. Every checkpoint touches it:

- **`## Now`** — update so it reflects what just shipped (move the closed item to `## Done`) and what (if anything) is now in flight.
- **`## Done (recent)`** — add a pointer for the unit of work just completed: `**Title** (YYYY-MM-DD, commit `<short>`) — terse summary + workstream / archive link if applicable.` Aim for under ~500 chars; detail lives in the commit message and workstream doc. Drop the oldest entry if the section is at its 5-entry cap (CHU011 will fail otherwise).
- **`## Next` / `## Investigations`** — add follow-ups discovered during the work; mark check-boxes for items that just shipped and move them to `## Done`.

Each top-level bullet stays ≤5 bullet markers (lead + sub-bullets). If an entry needs more, promote to `plans/workstreams/<slug>.md` and link from a one-line pointer here.

## 5. Commit and push if the work is meaningful

If the changes form a coherent unit, commit and push them. Use the `git-commit` skill, then `git push`.

A coherent unit = one logical change that could be described in a single commit message subject line. The compression artifacts from step 3 and the `plans/next-up.md` refresh from step 4 ride along in the same commit — they are part of the unit of work, not a separate housekeeping commit.

If the work is partial and not yet meaningful, it's fine to leave it uncommitted — but say so.

## 6. Note anything unfinished

If you couldn't complete something, or noticed something that needs follow-up, say it explicitly. Don't let it get lost.

## Rules

- **This is fast.** Preflight takes a few seconds. Step 3 takes under a minute on the average session and is skipped entirely on routine ones. The whole checkpoint should fit inside two minutes.
- **Don't skip step 1.** A `git status` catches surprises — files you forgot, files you didn't mean to change, merge artifacts.
- **Don't skip step 2.** Preflight is the single gate. If it passes, CI will pass. Narrow checks miss cross-cutting breakage.
- **Step 3 is the compression tier.** `git log` is the journal. If you find yourself writing long planning-doc prose, stop and ask whether it should be a Pattern, a Learning, a Decision, or a commit-message body instead.
- **Step 4 is cheap.** A one-line `## Done` entry + a refreshed `## Now` is all most checkpoints need. Always do it — the next session reads `next-up.md` cold.
- **Commit and push early.** Small commits are easier to review and revert than large ones. The compression artifacts ride with the work — one commit, not two.
