---
name: task-checkpoint
description: Sanity check at the end of a unit of work — preflight green, plans/next-up.md refreshed, durable lessons lifted, commit pushed. Use after finishing a coherent unit of work (one that could carry a single commit subject), before yielding to the user.
---

# Task Checkpoint

Per [AGENTS.md → Keeping plans and docs current](../../../AGENTS.md), run this at the end of every unit of work — before telling the user you're done.

**Trigger gate.** Did you just complete a unit of work that could be described in one commit subject?  If no, you're not at a checkpoint — go finish the work.

**Hold this question as you walk the steps:** did the session produce a tradeoff, a reusable code shape, a non-obvious constraint, or an agent-rule violation?  Step 3 is where you act on the answer.

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

Must show: `Preflight passed`. If it fails because of your work, fix it before committing.  If preflight is already red and the failure isn't from your work, surface and stop — don't ship onto a broken `main` (per AGENTS.md).

## 3. Compress durable lessons before committing

This is the compression tier — without it, lessons get sealed into dated history entries or commit messages and stop being re-readable.

Ask: **did this session produce something that future sessions need to know without scrolling git log?** Walk the four homes and lift if any apply. Lift *now*, in the same commit as the work, so the dated entry (if any) can be terse.

- [ ] **Lifted one bullet** — or explicitly decided "routine session, no lift".  Default to lifting rather than skipping.  Bar is *"would I want to know this if I picked up cold"*, not *"is this a flagship insight"*.

| Home | Lift when the session produced… | Where it lives |
|------|--------------------------------|----------------|
| `plans/decisions/NNNN-*.md` | A tradeoff or structural choice future contributors will need to know *why* about | New ADR via the `new-decision` skill |
| `plans/patterns.md` | Reusable code shape, subprocess invocation, IDE wiring, transport contract — *how* to implement correctly | Append a section under the right heading |
| Inline code comment | A non-obvious constraint discovered the hard way (hardware quirk, third-party-tool gotcha, runtime-specific behavior) — anywhere a reader of the code might trip on the same surface | One-line `# `-comment next to the workaround; keep the prose in the commit message |
| `AGENTS.md` non-negotiables | An agent-facing rule whose violation already cost time | Append to the rules list |
| Commit message body | Narrative context, what was tried and rejected, the rationale a future reader will want when running `git log <range>` | The commit you're about to write |

## 4. Refresh `plans/next-up.md`

`next-up.md` is the agent-managed work queue and the single source of truth for what's in flight and what's queued.  No `## Done` section — `git log` carries history (AGENTS.md "Keeping plans and docs current").  Every checkpoint touches it:

- **`## Now`** — remove the bullet for what just shipped.  If Now is now empty, leave it empty.
- **`## Next` / `## Investigations`** — remove the bullet for any item that just shipped; add new follow-ups discovered during the work as one-line entries (promote to `plans/workstreams/<slug>.md` if the item needs more than a title).

Each top-level bullet stays at one line, no sub-bullets (CHU011).  If an entry would need more, promote to `plans/workstreams/<slug>.md` and link from a one-line pointer here.

The narrative of what shipped lives in the commit message you write in step 5.  A future agent picking up cold runs `git --no-pager log -20 --oneline` to see the recent landings.

## 5. Commit and push if the work is meaningful

If the changes form a coherent unit, commit and push them.  Use the `git-commit` skill, then `git push` (no flags — branch tracking handles it).

A coherent unit = one logical change that could be described in a single commit message subject line. The compression artifacts from step 3 and the `plans/next-up.md` refresh from step 4 ride along in the same commit — they are part of the unit of work, not a separate housekeeping commit.

If push fails (divergent remote, network), surface and stop — don't force-push.  The remote may have moved; investigate before retrying.

If the work is partial and not yet meaningful, it's fine to leave it uncommitted — but say so.

## 6. Note anything unfinished

If you couldn't complete something, or noticed something that needs follow-up, say it explicitly. Don't let it get lost.

## Done when

- Preflight green (or pre-existing red surfaced to the user and work paused).
- Step 3 either lifted one bullet or explicitly decided "routine session, no lift".
- `plans/next-up.md` reflects what just shipped: the matching `## Now` / `## Next` bullet removed; new follow-ups added.
- Commit pushed — or the work explicitly declared partial.

## Rules

- **This is fast.** Preflight takes a few seconds. Step 3 takes under a minute on the average session and is skipped entirely on routine ones. The whole checkpoint should fit inside two minutes.
- **Don't skip step 1.** A `git status` catches surprises — files you forgot, files you didn't mean to change, merge artifacts.
- **Don't skip step 2.** Preflight is the single gate. If it passes, CI will pass. Narrow checks miss cross-cutting breakage.
- **Step 3 is the compression tier.** `git log` is the journal — there's no separate dated-timeline file. If you find yourself writing long planning-doc prose, stop and ask whether it should be a Pattern, a Learning, a Decision, or a commit-message body instead.
- **Step 4 is cheap.** Removing the shipped bullet from `## Now` / `## Next` is all most checkpoints need. Always do it — the next session reads `next-up.md` cold.
- **Commit and push early.** Small commits are easier to review and revert than large ones. The compression artifacts ride with the work — one commit, not two.
