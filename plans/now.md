# Now

**30-second brain snapshot.** Refreshed every `task-checkpoint`. If this file is stale, that means the last session ended without checkpointing — fall back to `git log -10` and `plans/next-up.md`.

This is the front door. Everything else is deeper read.

---

- **Phase:** Phase 3b closed + config conventions pinned (ADR 0035 + 0036) + lazy-loading research published. Next: Phase 3a (`chumicro-wifi`) — first library that consumes both conventions (chumicro-config `from_dict` + Tier B PEP 562 lazy adapter pattern from the new investigation).
- **Last shipped:** Lazy-loading investigation — surveyed every library's import shape, verified PEP 562 `module __getattr__` is supported on both MP + CP via `MICROPY_MODULE_GETATTR`, generalised the workbench-only PEP 562 pattern in `plans/patterns.md` to apply to device libraries with per-runtime adapters or non-trivial submodule graphs (Tier B). New-library scaffolder updated to use absolute imports + emits a Tier A / Tier B comment. Open question: boot-cost benchmark when wifi gives us a 4-adapter library to compare eager vs lazy on.
- **In flight:** Phase 3a Slice 0 — `chumicro-wifi` scaffold + `WifiConfig` + `_templates/config.toml` + Tier B lazy-adapter pattern from day one.
- **Blocked on:** —
- **Last touched:** `libraries/kvstore/**`, `plans/decisions/0034-kvstore-api-and-backends.md`, `plans/{now,history,next-up}.md`. Four boards plugged in: Lolin S2 CP/MP, Pi Pico W CP/MP — exercises every kvstore backend across slices 2–5.

---

## How this file works

- One screen, never more. If a section grows past two lines, it belongs somewhere else.
- Overwritten, not appended. Older snapshots are recoverable from `git log plans/now.md`.
- The agent updates this in step 4 of `task-checkpoint`. Humans can update it manually too.
- "Phase" / "In flight" / "Blocked on" are the load-bearing fields. The others are convenience.

If you're an agent picking up cold: read this, then `git --no-pager log --oneline -20`, then `plans/next-up.md` if you need the queue. That's the warm-up. Everything else (`history.md`, `decisions/`, `patterns.md`, `learnings.md`, workstreams) is deep-dive on demand.
