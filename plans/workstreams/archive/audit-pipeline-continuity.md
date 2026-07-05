# Workstream: audit pipeline continuity — persistence, baseline carryover, waiver ledger, incremental re-audit

Status: **shipped 2026-07-05** (all four phases; see git log for the landing commit).  Originally proposed:  Directions decided in the 2026-06-12 `/audit-skill` discussion of audit-code + audit-branch (report: `.scratch/skill-audits/audit-code+audit-branch-20260612T013211Z.md`, items 55 / 56 / 64 / 66).

## Problem

Each audit run is an island.  `eval.json` and the human's selection vector live in a `mkdtemp` /tmp room that a reboot erases, so a re-audit of the same target re-finds everything: findings the human already skipped with a reason resurface as new noise, findings that were fixed are indistinguishable from findings that persist, and the full pipeline re-runs at full cost even when two files changed.

## Decided directions (2026-06-12)

- **Persistence on both skills.** audit-branch's step 5 now offers a copy of `eval.json` + `picker.html` + the selection blob into `.scratch/audits/<slug>-<UTC>/`; audit-code needs the same offer.  This directory is the substrate every other item reads.
- **Baseline carryover is agent-driven, never user-formed.**  The orchestrator globs `.scratch/audits/` for the same target at resolve time, announces the hit ("found a prior audit from <date>, carrying it as baseline"), and passes `--baseline` itself.  The user only sees stamped cards.
- **Fingerprint matcher** (file + symbol + defect fragment) is the shared piece: baseline stamping (new / persisting / resolved), prior-skip preloading, waiver-ledger matching, and incremental carry all key on it.  Home: a `_shared` helper both renderers import.
- **Waiver ledger lives in a central committed registry** (e.g. `plans/audit-waivers/`), written by the skill at skip-with-note time — each entry is the quoted human note + finding fingerprint + date, so the merger's suppression always traces to a human decision and the file is ledger-formatted because the skill writes it.  Consulted via staging; never the orchestrator filtering on its own authority (audit-branch invariant 11 stays intact).
- **Waiver ledger and incremental mode split the problem:** the ledger handles the *noise* half (skipped findings stop resurfacing, even on full re-runs); incremental mode handles the *cost* half (a re-audit of the same branch stages only files changed since the last audited head, lenses pay for the delta, carried findings get a cheap validator re-check instead of a fresh lens pass) plus resolution tracking (applied/resolved status carries forward).  Prior art: CodeRabbit's incremental per-push reviews.
- **Deferred:** measured-coverage room inputs (pytest --cov missing lines, diff-cover changed-line intersection, mutmut surviving mutants) — saved as a candidate for a separate skill rather than this pipeline (user call, 2026-06-12).

## Implementation phases

1. **Persistence parity.**  Mirror audit-branch's step-5 persistence offer into audit-code's step 4; both skills copy the selection blob into the same `.scratch/audits/<slug>-<UTC>/` dir after the selection gate.
2. **Fingerprint matcher + baseline render.**  `_shared` helper matching findings by file + symbol + defect fragment; `render_eval.py` / `render_branch.py` accept `--baseline <prior eval.json>` and stamp cards new / persisting / resolved, preloading prior skip-with-note picks as page defaults with the note shown.  Orchestrator prose in both SKILL.md files: glob, announce, pass — no user action.
3. **Waiver ledger.**  `plans/audit-waivers/` entry format; skill writes an entry at skip-with-note; staging copies matching waivers into the room; the merger's actionability gate consults them and marks suppressions with the quoted note.
4. **Incremental re-audit.**  Prior-run detection from the persistence dir, delta staging (`prior-head..new-head`), carried-finding validator re-check, greyed carried cards with status chips on the page.

## Validation history

- (none yet)
