# Now

**30-second brain snapshot.** Refreshed every `task-checkpoint`. If this file is stale, that means the last session ended without checkpointing — fall back to `git log -10` and `plans/next-up.md`.

This is the front door. Everything else is deeper read.

---

- **Phase:** Project-workspace Phase 2 (`chumicro-repl`) shipped 2026-04-25; queue is between phases. Next sequenced phase is 3 (`chumicro-kvstore` + `chumicro-wifi`, can interleave).
- **Last shipped:** Pre-merge gates extended to workbench *and* `check_api` finally fires (griffe absolute-`--search` was a silent no-op).  Codified the regression coverage as `scripts/audit_gates.py` — 12 scenarios in ~1.5 s, run on demand.  Surfaced one open gap: the libraries/ absolute-imports rule has no static gate.
- **In flight:** —
- **Blocked on:** —
- **Last touched:** `scripts/{workspace,check_version,check_api}.py`, `scripts/tests/{test_workspace,test_check_version}.py`, `plans/{now,history,next-up}.md`. The non-zero workbench `VERSION` bump is now safe whenever — gates are exercised end-to-end first.

---

## How this file works

- One screen, never more. If a section grows past two lines, it belongs somewhere else.
- Overwritten, not appended. Older snapshots are recoverable from `git log plans/now.md`.
- The agent updates this in step 4 of `task-checkpoint`. Humans can update it manually too.
- "Phase" / "In flight" / "Blocked on" are the load-bearing fields. The others are convenience.

If you're an agent picking up cold: read this, then `git --no-pager log --oneline -20`, then `plans/next-up.md` if you need the queue. That's the warm-up. Everything else (`history.md`, `decisions/`, `patterns.md`, `learnings.md`, workstreams) is deep-dive on demand.
