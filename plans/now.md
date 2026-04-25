# Now

**30-second brain snapshot.** Refreshed every `task-checkpoint`. If this file is stale, that means the last session ended without checkpointing — fall back to `git log -10` and `plans/next-up.md`.

This is the front door. Everything else is deeper read.

---

- **Phase:** Phase 3b closed + config conventions pinned (ADR 0035 file structure, ADR 0036 `chumicro-config` library + templating convention). Next: Phase 3a (`chumicro-wifi`) consumes `chumicro-config` end-to-end (typed `from_dict` + ships its own `_templates/config.toml`).
- **Last shipped:** `chumicro-config` extended with `templates.get_section_template()` + an end-to-end example + 4 on-device functional tests on Pi Pico W MP. ADR 0036 §5 codifies the per-library template-shipping convention so workspace tooling (Phase 4a) can assemble starter `config.toml` files when libraries are added to a thing.
- **In flight:** Phase 3a Slice 0 — `chumicro-wifi` scaffold + `WifiConfig` + `_templates/config.toml`.
- **Blocked on:** —
- **Last touched:** `libraries/kvstore/**`, `plans/decisions/0034-kvstore-api-and-backends.md`, `plans/{now,history,next-up}.md`. Four boards plugged in: Lolin S2 CP/MP, Pi Pico W CP/MP — exercises every kvstore backend across slices 2–5.

---

## How this file works

- One screen, never more. If a section grows past two lines, it belongs somewhere else.
- Overwritten, not appended. Older snapshots are recoverable from `git log plans/now.md`.
- The agent updates this in step 4 of `task-checkpoint`. Humans can update it manually too.
- "Phase" / "In flight" / "Blocked on" are the load-bearing fields. The others are convenience.

If you're an agent picking up cold: read this, then `git --no-pager log --oneline -20`, then `plans/next-up.md` if you need the queue. That's the warm-up. Everything else (`history.md`, `decisions/`, `patterns.md`, `learnings.md`, workstreams) is deep-dive on demand.
