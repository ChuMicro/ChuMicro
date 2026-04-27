# Now

**30-second brain snapshot.** Refreshed every `task-checkpoint`. If this file is stale, that means the last session ended without checkpointing — fall back to `git log -10` and `plans/next-up.md`.

This is the front door. Everything else is deeper read.

---

- **Phase:** **Workspace ecosystem completion — planned, awaiting new session to execute.**  Project-workspace closed (Phase 7, 2026-04-27).  OTA carved out to its own unscoped workstream (`plans/workstreams/ota.md`).  Next focused work pass is laid out in `plans/workstreams/workspace-ecosystem.md` (umbrella) with a detailed Phase 1 plan in `plans/workstreams/nested-things-and-examples.md`.  No code shipped under this workstream yet; this session was planning-only at the user's request.
- **Last shipped:** `b75bad9` — OTA carved out into its own unscoped workstream so project-workspace could close clean.  Project-workspace status now `complete`.
- **In flight:** —
- **Blocked on:** —
- **Last touched:** `plans/workstreams/workspace-ecosystem.md` (new — umbrella for Phases 1-6), `plans/workstreams/nested-things-and-examples.md` (new — detailed Phase 1 plan), `plans/now.md` (this file), `plans/next-up.md` (queue refresh).

---

## What a fresh session should read first

1. This file (`plans/now.md`).
2. `plans/workstreams/workspace-ecosystem.md` — the umbrella workstream covering the next 6 phases.
3. `plans/workstreams/nested-things-and-examples.md` — detailed Phase 1 plan (slices 1-6, file lists, acceptance per slice).
4. `plans/next-up.md` — queue + done log.

## Phase summary (priority order)

| Phase | What | Detail | Estimated |
|---|---|---|---|
| **1** | Nested things layout + `examples/` folder in template | `nested-things-and-examples.md` | 2-3 sessions, ~600 LOC + 10 new files |
| **2** | Workspace ergonomics: `status`, `doctor`, `deploy --dry-run`, `deploy --watch` | umbrella §Phase 2 | 1 session per command (~50-200 LOC each) |
| **3** | `new_library_scaffold.py` → `chumicro-workspace new --library` | umbrella §Phase 3 | 1 session, ~250 LOC moved |
| **4** | Wire `workspace.yml` `lint` / `coverage_threshold` / `agent_strictness` knobs | umbrella §Phase 4 | <1 session, ~150 LOC |
| **5** | Documentation audit pass | umbrella §Phase 5 | Half session, no new code |
| **6** | Richer REPL Phases 1a/b/c (parallel track) | `repl-playground.md` §Phase 1 | ~600 LOC across 3 sub-phases |

## Constraints the executor needs to know

* **No backward compatibility.**  Nothing has been published to PyPI.  Change file formats, CLI flag shapes, on-device shim layouts freely.  Do NOT add migration logic.
* **Two-repo flow.**  Phases 1, 2, 3, 4 each touch the chumicro mono-repo.  Phases 1 + 5 also touch the [`ChuMicro-Workspace-Template`](https://github.com/ChuMicro/ChuMicro-Workspace-Template) repo (local clone at `/Users/chuxor/circuitpython/ChuMicro-Workspace-Template`).
* **Templates live in `_payloads/`.**  The canonical scaffolds (thing, library, examples) live under `workbench/workspace/src/chumicro_workspace/_payloads/`.  The template repo's `_templates/` is a *user-owned-config materialisation source* — not where scaffolds belong.
* **Task-checkpoint per slice.**  Every slice ends with a green preflight + commit + push.  Don't batch slices.

## What's explicitly out of scope for this workstream

(All preserved in `plans/next-up.md` queue.)

* Rebrand ChuMicro → ChipPy
* OTA (`plans/workstreams/ota.md`, unscoped)
* Multi-thing-staging cleanup (waits for "build a real second simple thing" trigger)
* `pytest_device` `_test_creds` deploy bridge
* `generate_config_files.py` calling `chumicro_workspace` directly
* Per-runtime adapter helper extraction
* Expand device test matrix beyond ESP32-S2
* Performance benchmarking infrastructure

## How this file works

- One screen, never more.
- Overwritten, not appended.  Older snapshots are recoverable from `git log plans/now.md`.
- Updated in step 4 of `task-checkpoint`.

If you're an agent picking up cold: read this, then `git --no-pager log --oneline -20`, then `plans/next-up.md` if you need the queue.
