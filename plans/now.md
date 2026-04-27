# Now

**30-second brain snapshot.** Refreshed every `task-checkpoint`. If this file is stale, that means the last session ended without checkpointing — fall back to `git log -10` and `plans/next-up.md`.

This is the front door. Everything else is deeper read.

---

- **Phase:** **Workspace ecosystem completion — planned, awaiting new session to execute.**  Project-workspace closed (Phase 7, 2026-04-27).  OTA carved out (`plans/workstreams/ota.md`, unscoped).  Next focused work pass laid out in `plans/workstreams/workspace-ecosystem.md` (umbrella) with Phase 1 detail in `plans/workstreams/nested-things-and-examples.md`.  Plan revised 2026-04-27 with user triage on the original Plan C list — see "Phase summary" below.  No code shipped under this workstream yet.
- **Last shipped:** `68ab5b3` — initial planning bundle.  Revisions in this session refine Phase 2, add Phase 3 (per-env deploys, bumped up), drop the `switch` command into Phase 1 Slice 7, document deferred items.
- **In flight:** —
- **Blocked on:** —
- **Last touched:** `plans/workstreams/workspace-ecosystem.md` (revised), `plans/workstreams/nested-things-and-examples.md` (added Slice 7 — drop switch), `plans/now.md` (this file), `plans/next-up.md` (untouched in this revision — content stays accurate).

---

## What a fresh session should read first

1. This file (`plans/now.md`).
2. `plans/workstreams/workspace-ecosystem.md` — umbrella covering 7 phases (revised).
3. `plans/workstreams/nested-things-and-examples.md` — Phase 1 detail (slices 1-7, file lists, acceptance per slice).
4. `plans/next-up.md` — queue + done log.

## Phase summary (revised after user triage)

| Phase | What | Detail | Estimated |
|---|---|---|---|
| **1** | Nested things + `examples/` folder + drop `switch` | `nested-things-and-examples.md` | 2-3 sessions, ~600 LOC + 10 new files |
| **2** | Ergonomics quick wins: `status`, `doctor`, `deploy --dry-run`, app-level error recovery hints, `repl --tail <thing>` auto-deploy, multi-device deploy (assess) | umbrella §Phase 2 (six sub-items 2a-2f) | 1 session per sub-item |
| **3** | Per-environment deploys (bumped up — "before it gets hard") | umbrella §Phase 3 | ~250 LOC, 1 session |
| **4** | `new_library_scaffold.py` → `chumicro-workspace new --library` | umbrella §Phase 4 | ~250 LOC moved, 1 session |
| **5** | Wire `workspace.yml` quality knobs (`lint` / `coverage` / `agent_strictness`) | umbrella §Phase 5 | ~150 LOC |
| **6** | Documentation audit pass | umbrella §Phase 6 | Half session, no new code |
| **7** | Richer REPL Phases 1a/b/c (parallel track) | `repl-playground.md` §Phase 1 | ~600 LOC across 3 sub-phases |

## What the user explicitly deferred this round

| Item | Reason captured in umbrella's "Out of scope" |
|---|---|
| `deploy --watch` (file-watcher auto-deploy) | "Save for a rainy day" |
| `edit <thing>` (open both files in $EDITOR) | IDE/vim users handle this themselves |
| Multi-device deploys (Phase 2f), if not cheap | Conditional on first-step design sketch — assess before shipping |
| Persistent `logs <device>` capture | Open design question — REPL concern vs workspace concern; revisit later |

## Constraints the executor needs to know

* **No backward compatibility.**  Nothing has been published to PyPI.  Change file formats, CLI flag shapes, on-device shim layouts, and remove commands (e.g. `switch`) freely.  Do NOT add migration logic.
* **Two-repo flow.**  Phases 1, 2, 3, 4, 5 each touch the chumicro mono-repo.  Phases 1 + 6 also touch the [`ChuMicro-Workspace-Template`](https://github.com/ChuMicro/ChuMicro-Workspace-Template) repo (local clone at `/Users/chuxor/circuitpython/ChuMicro-Workspace-Template`).
* **Templates live in `_payloads/`.**  Canonical scaffolds (thing, library, examples) live under `workbench/workspace/src/chumicro_workspace/_payloads/`.  The template repo's `_templates/` is a *user-owned-config materialisation source* (secrets.yml etc.) — not where scaffolds belong.
* **Task-checkpoint per slice.**  Every slice ends with a green preflight + commit + push.  Don't batch slices.

## What's explicitly out of scope for this workstream

(All preserved in `plans/next-up.md` queue.)

* Rebrand ChuMicro → ChipPy
* OTA (`plans/workstreams/ota.md`, unscoped)
* Multi-thing-staging cleanup (partly subsumed by Phase 1 Slice 7 dropping `switch`; the rest waits for "build a real second simple thing" trigger)
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
