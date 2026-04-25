# Now

**30-second brain snapshot.** Refreshed every `task-checkpoint`. If this file is stale, that means the last session ended without checkpointing — fall back to `git log -10` and `plans/next-up.md`.

This is the front door. Everything else is deeper read.

---

- **Phase:** Project-workspace Phase 2 (`chumicro-repl`) shipped 2026-04-25; queue is between phases. Next sequenced phase is 3 (`chumicro-kvstore` + `chumicro-wifi`, can interleave).
- **Last shipped:** Planning-ecosystem restructure — compression ritual in `task-checkpoint`, `plans/now.md` front door, `plans/learnings.md`, `history.md` reframed as the synthesized layer (this commit).
- **In flight:** —
- **Blocked on:** —
- **Last touched:** `plans/{now,learnings,history,patterns,README,next-up}.md`, `.github/skills/task-checkpoint/SKILL.md`. Other agent shipped `fa8628c` covering workbench packages in `release.yml` + `promote.yml` (still 0.0.0, no release fires yet); follow-up in `next-up.md` to extend `check-version` + `check-api` before any non-zero workbench bump.

---

## How this file works

- One screen, never more. If a section grows past two lines, it belongs somewhere else.
- Overwritten, not appended. Older snapshots are recoverable from `git log plans/now.md`.
- The agent updates this in step 4 of `task-checkpoint`. Humans can update it manually too.
- "Phase" / "In flight" / "Blocked on" are the load-bearing fields. The others are convenience.

If you're an agent picking up cold: read this, then `git --no-pager log --oneline -20`, then `plans/next-up.md` if you need the queue. That's the warm-up. Everything else (`history.md`, `decisions/`, `patterns.md`, `learnings.md`, workstreams) is deep-dive on demand.
