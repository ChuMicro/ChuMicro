# Now

**30-second brain snapshot.** Refreshed every `task-checkpoint`. If this file is stale, that means the last session ended without checkpointing — fall back to `git log -10` and `plans/next-up.md`.

This is the front door. Everything else is deeper read.

---

- **Phase:** Phase 3b closed 2026-04-25 + Decision 0035 (runtime config structure) drafted as Phase 3a prereq. Next: Phase 3a (`chumicro-wifi`) — first library that consumes a config section per the new convention.
- **Last shipped:** Decision 0035 — runtime config layout: section-namespaced dict at `/runtime_config.msgpack`, section key = library basename without `chumicro-` prefix, library ships `<Name>Config.from_dict()` classmethod, no schema registry (each library validates its own slice at runtime), deep per-key merge across `workspace.yml` + `things/<name>/config.toml` + `secrets.yml`.
- **In flight:** Phase 3a Slice 0 — `chumicro-wifi` skeleton + `WifiConfig` + `WifiConfig.from_dict` per ADR 0035.
- **Blocked on:** —
- **Last touched:** `libraries/kvstore/**`, `plans/decisions/0034-kvstore-api-and-backends.md`, `plans/{now,history,next-up}.md`. Four boards plugged in: Lolin S2 CP/MP, Pi Pico W CP/MP — exercises every kvstore backend across slices 2–5.

---

## How this file works

- One screen, never more. If a section grows past two lines, it belongs somewhere else.
- Overwritten, not appended. Older snapshots are recoverable from `git log plans/now.md`.
- The agent updates this in step 4 of `task-checkpoint`. Humans can update it manually too.
- "Phase" / "In flight" / "Blocked on" are the load-bearing fields. The others are convenience.

If you're an agent picking up cold: read this, then `git --no-pager log --oneline -20`, then `plans/next-up.md` if you need the queue. That's the warm-up. Everything else (`history.md`, `decisions/`, `patterns.md`, `learnings.md`, workstreams) is deep-dive on demand.
