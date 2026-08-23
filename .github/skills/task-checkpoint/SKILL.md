---
name: task-checkpoint
description: Sanity check at the end of a unit of work — preflight green, plans/next-up.md refreshed, durable lessons lifted, commit pushed. Use after finishing a coherent unit of work (one that could carry a single commit subject). Multiple checkpoints can ride the same session; the yield happens once when the named work is done, not after every unit.
---

# Task Checkpoint

Per [AGENTS.md → Workflow](../../../AGENTS.md#workflow), run this at the end of every unit of work — before moving on to the next unit or telling the user you're done.

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
- Are there modifications I didn't make this session?  If yes, surface them to the user *before* running step 2 — preflight will likely fail on someone else's red and waste the slow gate.  When you stage in step 5, use explicit pathspecs (never `git add .` / `git add -A`) so the pre-existing dirt doesn't ride into your commit.
- Did I leave any temporary or scratch files outside `.scratch/`?

## 2. Run preflight

```bash
set -o pipefail; python scripts/run.py preflight --coverage-threshold 94 2>&1 | tail -5
```

Must show: `Preflight passed`. The `pipefail` is load-bearing: without it the pipeline reports `tail`'s exit status, and an `&&` chain hung off this command will happily commit and push a red tree (this shipped a CHU012 failure to main on 2026-07-05).  Never fuse this command with the commit in one `&&` chain — run the gate, read its verdict, then commit.  If it fails because of your work, fix it before committing.  If preflight is already red and the failure isn't from your work, surface and stop — don't ship onto a broken `main` (per AGENTS.md).

## 3. Compress durable lessons before committing

This is the compression tier — without it, lessons get sealed into dated history entries or commit messages and stop being re-readable.

Ask: **did this session produce something that future sessions need to know without scrolling git log?** Walk the four destinations below and lift if any apply. Lift *now*, in the same commit as the work, so the dated entry (if any) can be terse.

- [ ] **Lifted one bullet** — or explicitly decided "routine session, no lift".  Default to lifting rather than skipping.  Bar is *"would I want to know this if I picked up cold"*, not *"is this a flagship insight"*.

| Destination | Lift when the session produced… | How to write it |
|-------------|---------------------------------|------------------|
| `plans/decisions/NNNN-*.md` | A tradeoff or structural choice future contributors will need to know *why* about | New ADR via the `new-decision` skill |
| `plans/patterns.md` | Reusable code shape, subprocess invocation, IDE wiring, transport contract — *how* to implement correctly | Append a section under the right heading |
| Inline code comment | A non-obvious constraint discovered the hard way (hardware quirk, third-party-tool gotcha, runtime-specific behavior) — anywhere a reader of the code might trip on the same surface | One-line `# `-comment next to the workaround; keep the prose in the commit message |
| `AGENTS.md` non-negotiables | An agent-facing rule whose violation already cost time | Append to the rules list |

Narrative context, what was tried and rejected, and the rationale a future reader will want when running `git log <range>` go in the commit message body you're about to write.  That's the default; the table above is for the durable-lesson exceptions worth their own destination.

## 4. Refresh `plans/next-up.md`

Per [AGENTS.md → Workflow](../../../AGENTS.md#workflow), every checkpoint refreshes `plans/next-up.md`:

- Remove the bullet for what just shipped from whichever section held it.  `## Now` is typical; `## Next`, `## Out of scope`, and `## Investigations` are also valid (see [plans/README.md](../../../plans/README.md) for the section list).
- Add follow-ups discovered during the work as one-line entries under `## Next`.  If an entry would need more than a title, promote to `plans/workstreams/<slug>.md` and link from a one-line pointer here (enforced by CHU011).

A future agent picking up cold reads `next-up.md` for what's queued and runs `git --no-pager log -20 --oneline` for what just landed.

## 5. Commit and push if the work is meaningful

If the changes form a coherent unit, commit them.  Use the `git-commit` skill.

`main` is PR-only ([Decision 0120](../../../plans/decisions/0120-main-is-pr-only.md)), so the commit rides a topic branch, never `main` directly:

- Already on a topic branch: `git push` (no flags — branch tracking handles it), then open a PR with `gh pr create --fill` if one doesn't exist yet; a later checkpoint on the same branch just pushes and the open PR updates.
- Still on `main` with work committed locally: you took a wrong turn earlier — move the work to a branch (`git checkout -b <type>/<slug>`), push that, open the PR, and leave local `main` pointing back at `origin/main`.

A coherent unit = one logical change that could be described in a single commit message subject line. The compression artifacts from step 3 and the `plans/next-up.md` refresh from step 4 ride along in the same commit — they are part of the unit of work, not a separate housekeeping commit.

If push fails (divergent remote, network), surface and stop — don't force-push.  The remote may have moved; investigate before retrying.

If the work is partial and not yet meaningful, it's fine to leave it uncommitted — but say so.

## 6. Note anything unfinished

If you couldn't complete something, or noticed something that needs follow-up, say it explicitly. Don't let it get lost.

## Done when

- Preflight green (or pre-existing red surfaced to the user and work paused).
- Step 3 either lifted one bullet or explicitly decided "routine session, no lift".
- `plans/next-up.md` reflects what just shipped: the shipped bullet removed from whichever section held it; new follow-ups added under `## Next`.
- Commit pushed on a topic branch with a PR open — or the work explicitly declared partial.

## Rules

- **This is fast.** Preflight takes a few seconds. Step 3 takes under a minute on the average session and is skipped entirely on routine ones. The whole checkpoint should fit inside two minutes.
- **Don't skip step 1.** A `git status` catches surprises — files you forgot, files you didn't mean to change, merge artifacts.
- **Don't skip step 2.** Preflight is the single gate. If it passes, CI will pass. Narrow checks miss cross-cutting breakage.
- **One commit, not two.** The step 3 compression artifacts and the step 4 `next-up.md` refresh ride with the work commit. No separate housekeeping commit.
