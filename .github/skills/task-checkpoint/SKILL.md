---
name: task-checkpoint
description: Sanity check at the end of a unit of work: preflight green, workstream and docs refreshed, plans/next-up.md refreshed, durable lessons lifted, commit pushed. Use after finishing a coherent unit of work (one that could carry a single commit subject). Multiple checkpoints can ride the same session; the yield happens once when the named work is done, not after every unit.
---

# Task Checkpoint

Per [AGENTS.md → Workflow](../../../AGENTS.md#workflow), run this at the end of every unit of work — before moving on to the next unit or telling the user you're done.

**Trigger gate.** Did you just complete a unit of work that could be described in one commit subject?  If no, you're not at a checkpoint — go finish the work.

**Hold this question as you walk the steps:** did the session produce a tradeoff, a reusable code shape, a non-obvious constraint, or an agent-rule violation?  Step 3 is where you act on the answer.

## 1. Review what changed

```bash
git --no-pager status --short
git --no-pager diff --stat
git --no-pager worktree list
```

Scan the output. Ask yourself:
- Are there files I changed that I forgot about?
- Are there files I didn't mean to change?
- Are there modifications I didn't make this session?  If yes, surface them to the user *before* running step 2 — preflight will likely fail on someone else's red and waste the slow gate.  When you stage in step 6, use explicit pathspecs (never `git add .` / `git add -A`) so the pre-existing dirt doesn't ride into your commit.
- Did I leave any temporary or scratch files outside `.scratch/`?

## 2. Run preflight

```bash
python scripts/run.py preflight --coverage-threshold 94 --quiet > .scratch/preflight.txt 2>&1; echo "EXIT=$?"
```

Then read `.scratch/preflight.txt`.  Do not pipe the gate through `tail`, `head`, or `grep`.  Two separate failures come from piping it:

- A pipeline reports the last stage's exit status, so an `&&` chain hung off `| tail` will happily commit and push a red tree.  This shipped a CHU012 failure to main on 2026-07-05.
- Phases do not print their verdict last.  `run.py lint` prints ruff's `All checks passed!` *before* the `chumicro-checks` findings, so a `head` or a short `tail` shows green while the run is red.

Read the file and confirm the phase summary shows `PASS` on every row and the run ends with `Preflight passed`.  Never fuse the gate with the commit in one `&&` chain: run it, read the verdict, then commit.  If it fails because of your work, fix it first.  If preflight is already red and the failure is not yours, surface and stop rather than shipping onto a broken `main`.

## 3. Compress durable lessons before committing

This is the compression tier — without it, lessons get sealed into dated history entries or commit messages and stop being re-readable.

Ask: **did this session produce something that future sessions need to know without scrolling git log?** Walk the destinations below and lift if any apply. Lift *now*, in the same commit as the work, so the dated entry (if any) can be terse.

- [ ] **Lifted one bullet** — or explicitly decided "routine session, no lift".  Default to lifting rather than skipping.  Bar is *"would I want to know this if I picked up cold"*, not *"is this a flagship insight"*.

| Destination | Lift when the session produced… | How to write it |
|-------------|---------------------------------|------------------|
| `plans/decisions/NNNN-*.md` | A tradeoff or structural choice future contributors will need to know *why* about | New ADR via the `new-decision` skill |
| `plans/patterns.md` | Reusable code shape, subprocess invocation, IDE wiring, transport contract — *how* to implement correctly | Append a section under the right heading |
| Inline code comment | A non-obvious constraint discovered the hard way (hardware quirk, third-party-tool gotcha, runtime-specific behavior) — anywhere a reader of the code might trip on the same surface | One-line `# `-comment next to the workaround; keep the prose in the commit message |
| `AGENTS.md` | An agent-facing rule whose violation already cost time, and that applies to every session | Append to the matching section (Workflow, Working style, Research) |
| `.claude/rules/<tree>.md` | The same, but scoped to one tree (library code, tests, workbench, comments) | Append there instead, so it loads only when a matching file is opened |
| `plans/field-notes/` | A hardware behavior, a bench measurement, a tooling trap, or session narration that is not a rule | Append to the matching topic file, with the board, runtime, and command named |

Narrative context, what was tried and rejected, and the rationale a future reader will want when running `git log <range>` go in the commit message body you're about to write.  That's the default; the table above is for the durable-lesson exceptions worth their own destination.

## 4. Refresh the workstream and the docs your change touched

Working code is not a finished unit of work.  Walk these and fix what your change made wrong, in this same commit:

- [ ] **Workstream.**  If the work came from a `plans/workstreams/<name>.md` phase, append one line to its `## Validation history` and update `Status:` (`shipped` / `parked` / `superseded`) when the whole file is done.  A workstream still describing shipped work as unshipped is work the next session redoes.
- [ ] **ADR bodies.**  A decision whose shape changed gets an in-place body edit, never an `## Update` banner (enforced by `CHU024`).
- [ ] **User docs.**  A changed command, flag, config key, or behavior means `docs/` and the library `README.md` / `docs/guide.md` are now wrong.  Ask: *if someone reads the docs tomorrow, will they find correct information?*
- [ ] **Scaffold templates and CI.**  A new rule or layout means `new-library`'s templates and the workflow files may need the same edit.
- [ ] **Lintable drift.**  If the drift class you just fixed by hand could be caught deterministically, say so in the commit body or open a `CHU` follow-up ([Decision 0074](../../../plans/decisions/0074-drift-mechanization-as-project-policy.md)).

## 5. Refresh `plans/next-up.md`

Per [AGENTS.md → Workflow](../../../AGENTS.md#workflow), every checkpoint refreshes `plans/next-up.md`:

- Remove the bullet for what just shipped from whichever section held it.  `## Now` is typical; `## Next`, `## Out of scope`, and `## Investigations` are also valid (see [plans/README.md](../../../plans/README.md) for the section list).
- Add follow-ups discovered during the work as one-line entries under `## Next`.  If an entry would need more than a title, promote to `plans/workstreams/<slug>.md` and link from a one-line pointer here (enforced by CHU011).

A future agent picking up cold reads `next-up.md` for what's queued and runs `git --no-pager log -20 --oneline` for what just landed.

## 6. Commit and push if the work is meaningful

If the changes form a coherent unit, commit them.  Use the `git-commit` skill.

`main` is PR-only ([Decision 0120](../../../plans/decisions/0120-main-is-pr-only.md)), so the commit rides a topic branch, never `main` directly:

- Already on a topic branch: `git push` (no flags — branch tracking handles it), then open a PR with `gh pr create --fill` if one doesn't exist yet; a later checkpoint on the same branch just pushes and the open PR updates.
- Still on `main` with work committed locally: you took a wrong turn earlier — move the work to a branch (`git checkout -b <type>/<slug>`), push that, open the PR, and leave local `main` pointing back at `origin/main`.

A coherent unit = one logical change that could be described in a single commit message subject line. The compression artifacts from step 3, the doc and workstream refresh from step 4, and the `plans/next-up.md` refresh from step 5 ride along in the same commit — they are part of the unit of work, not a separate housekeeping commit.

If push fails (divergent remote, network), surface and stop — don't force-push.  The remote may have moved; investigate before retrying.

If the work is partial and not yet meaningful, it's fine to leave it uncommitted — but say so.

## 7. Note anything unfinished

If you couldn't complete something, or noticed something that needs follow-up, say it explicitly. Don't let it get lost.

## Done when

- Preflight green, read from the file rather than a pipe (or pre-existing red surfaced to the user and work paused).
- Step 3 either lifted one bullet or explicitly decided "routine session, no lift".
- Step 4 walked: the workstream, ADR bodies, user docs, scaffold templates, and CI config your change touched are correct in this commit.
- `plans/next-up.md` reflects what just shipped: the shipped bullet removed from whichever section held it; new follow-ups added under `## Next`.
- Commit pushed on a topic branch with a PR open — or the work explicitly declared partial.

## Rules

- **This is fast.** Preflight is well under a minute. Steps 3 and 4 take a minute on the average session and collapse to a quick no-op on routine ones.
- **Don't skip step 1.** A `git status` catches surprises — files you forgot, files you didn't mean to change, merge artifacts.
- **Don't skip step 2.** Preflight is the single gate. If it passes, CI will pass. Narrow checks miss cross-cutting breakage.
- **Don't skip step 4.** Code that works with a stale workstream or a wrong doc is not a finished unit of work. This is the step that most often gets dropped.
- **One commit, not two.** The step 3 compression artifacts, the step 4 doc and workstream refresh, and the step 5 `next-up.md` refresh ride with the work commit. No separate housekeeping commit.
- **Never pipe the gate.** Redirect preflight to `.scratch/` and read the file. A phase can print its pass line before its findings, so a piped `head` or `tail` reports green on a red run.
- **Check for company.** `git --no-pager worktree list` and a `git status` that shows changes you did not make both mean another session is live. Surface it before you stage.
