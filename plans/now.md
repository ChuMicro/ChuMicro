# Now

**30-second brain snapshot.** Refreshed every `task-checkpoint`. If this file is stale, that means the last session ended without checkpointing — fall back to `git log -10` and `plans/next-up.md`.

This is the front door. Everything else is deeper read.

---

- **Phase:** **Backlog cleanup + plan-validation pass.**  Knocked off three small items, validated project-workspace status, and drafted a concrete Phase 1 implementation plan for the richer-REPL workstream.  Next step is the user's go/no-go on starting REPL Phase 1a.
- **Last shipped:**
  * `4019e24` — sockets functional tests (`test_real_tcp.py` + `test_real_tls.py` + `conftest.py`) + `scripts/tests/test_generate_config_files.py` schema-validation gate.  4/4 generate-config tests pass.  Sockets tests skip cleanly without `_test_creds`; will run live once `pytest_device` deploys the shim.
- **In flight:** —
- **Blocked on:** —
- **Last touched:** `libraries/sockets/functional_tests/{conftest.py,test_real_tcp.py,test_real_tls.py}` (new), `scripts/tests/test_generate_config_files.py` (new), `plans/workstreams/project-workspace.md` (Phase 7 Layer-2 marked done — was already shipped, doc was stale), `plans/workstreams/repl-playground.md` (concrete Phase 1 implementation plan added).

---

## Project-workspace status — VALIDATED + CLOSED 2026-04-27

User asked to confirm whether the project-workspace plans are done.  **They are.**  Application-level OTA was carved out into its own potential workstream at `plans/workstreams/ota.md` (`unscoped`) so this workstream could close cleanly — preserves the idea as a discrete thing-to-do without forcing it to live as a permanent open phase on the parent workstream.

| Phase | Status |
|---|---|
| 1 — `chumicro-deploy` extraction | ✅ Complete (2026-04-22) |
| 2 — `chumicro-repl` minimum-viable | ✅ Complete (2026-04-25) |
| 3a — `chumicro-wifi` | ✅ Complete (2026-04-25) |
| 3b — `chumicro-kvstore` + config pipeline | ✅ Complete (2026-04-25) |
| 4a — `chumicro-workspace` | ✅ Complete (2026-04-25) |
| 4b — workspace template | ✅ Superseded by Decision 0038 (clone-the-repo bootstrap; `init` / `update` folded into `chumicro-workspace`) |
| 4c — template companion repo | ✅ Dissolved into Decision 0038 (the template *is* the repo) |
| 5 — `chumicro-sockets` | ✅ Complete (2026-04-25) |
| 6 — `chumicro-mqtt` | ✅ Complete (2026-04-26) |
| 7 — first sensor thing template | ✅ **Closed 2026-04-27** — Layer-1 (CPython import resolves), Layer-2 (deploy + phase-marker assert via fail-fast wifi config), Layer-3 (live broker round-trip), sensor thing source, README walkthrough — all shipped.  Doc previously listed Layer-2 as open; was already in `test_sensor_thing_reaches_boot_phase_marker_on_*`.  Doc refreshed in this session. |

Application-level OTA, previously listed as Phase 8, **carved out** to its own potential workstream at `plans/workstreams/ota.md` — `unscoped` placeholder, idea preserved without occupying a permanent open phase on the parent workstream.  Trigger to revisit: a real thing on a wall / in a yard that needs an update without physical access.  Prior thinking remains at `plans/workstreams/project-workspace-research.md` §OTA.

Project-workspace.md status updated to `complete`.

## Richer REPL — concrete Phase 1 plan filed

`plans/workstreams/repl-playground.md` — added a 70-line "Phase 1 implementation plan" subsection.  Three input modes (passthrough / line / edit), hot-toggleable; `prompt_toolkit` joins as a workbench-only dep; per-device persistent history under `~/.chumicro-repl/history/<uid>/`.  Three sub-phases:

* **Phase 1a** — line mode + persistent history.  ~250 LOC.  Smallest viable.  Outcome: every session has cursor edit, up-arrow history, `Ctrl-R` reverse search, per-device isolation.  No new `:` commands yet — foundation in place.
* **Phase 1b** — `:edit` command (open `$EDITOR`, ship buffer).  Plus `:save` / `:load` / `:snippets`.  ~150 LOC.  Outcome: writing a 30-line function in the REPL stops being painful.
* **Phase 1c** — tab completion via on-device `dir()` query, with per-session cache + reset-detection invalidation.  ~200 LOC.  Outcome: REPL feels modern.

Total Phase 1 budget: ~600 LOC + tests.  Beats `mpremote` on every dimension that matters for interactive work.

## What's pending — pick one

* **Start REPL Phase 1a** (line mode + persistent history).  Self-contained, ships immediately useful UX.  Most concretely scoped on the queue.
* **Start REPL Phase 1b/c** (after 1a).  Builds on the same architecture.
* **`new_library_scaffold.py` → `chumicro-workspace new --library`** fold.  Smaller scope (~200 LOC migration).  Lower urgency since this only fires when adding a library to chumicro itself.
* **Whatever's not yet on next-up.md** — open call.

## How this file works

- One screen, never more.
- Overwritten, not appended.  Older snapshots are recoverable from `git log plans/now.md`.
- Updated in step 4 of `task-checkpoint`.

If you're an agent picking up cold: read this, then `git --no-pager log --oneline -20`, then `plans/next-up.md` if you need the queue.
