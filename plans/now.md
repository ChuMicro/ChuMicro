# Now

**30-second brain snapshot.** Refreshed every `task-checkpoint`. If this file is stale, that means the last session ended without checkpointing — fall back to `git log -10` and `plans/next-up.md`.

This is the front door. Everything else is deeper read.

---

- **Phase:** **ADR audit + cleanup sweep.**  Audited 48 ADRs (4 sub-agents in parallel) for date hygiene, status-enum compliance, banned dated-update sections, missing `Related:` fields, stale path references, length bloat, and missing high-level ADRs.  Phase 1 (mechanical sweep) and Phase 2 (stale-path fixes) have landed.  Phase 2 corrected `scripts/pytest_device.py` → `chumicro-pytest-device`, `support/device_transport/` → `workbench/deploy/`, `things/` → `projects/`, `_adapters/mp_esp32.py + mp_rp2.py` → `mp.py`; fixed 4 hallucinated intra-ADR link targets (0010, 0014, 0015, 0029 file basenames); past-tensed 0006 and 0008 Decision bodies; dropped 0042's "Pending decision" in-body blockquote.
- **Last shipped:** `plans/decisions: phase 2 audit cleanup — fix stale path refs and broken intra-ADR links` (this commit).
- **In flight:** ADR audit phases 3–4 — compact 12 length offenders (0035, 0034, 0041, 0036, 0048, 0042, 0040, 0032, 0013, 0033, 0027, 0045 — each over 150 lines, several reading as design docs), write 4–5 missing high-level ADRs (three-runtime philosophy, library inclusion test, runner-shaped policy, workbench/library import boundary, recovery philosophy).
- **Blocked on:** —.
- **Last touched:** 0006/0008 (past-tense), 0027/0028/0029/0030/0031/0032/0033/0035/0036/0038 (stale paths), 0039/0040/0041/0042/0045 (link targets).

---

## What a fresh session should read first

1. This file (`plans/now.md`).
2. `git --no-pager log --oneline -20` — what just shipped, in order.
3. `plans/next-up.md` — queue (`## Now`) + recent done log.
4. `plans/decisions/` — only when proposing structural changes.

## Pick-up candidates (sorted by readiness)

| Candidate | Where | Notes |
|---|---|---|
| Anything in `## Next` of `next-up.md` | `plans/next-up.md` | Rebrand to ChipPy, OTA workstream (`plans/workstreams/ota.md`), digital I/O library, performance benchmarking infrastructure, etc.  All are unscoped or trigger-gated. |

## Hard rules to remember (non-negotiables)

- **`AGENTS.md` non-negotiables apply.**  Read it on session start.
- **No backward compatibility burden.**  Nothing's published to PyPI yet — change formats, flags, layouts freely.  Do not add migration logic.
- **Task-checkpoint per slice.**  Every coherent unit ends with green preflight (`python scripts/run.py preflight --coverage-threshold 94`) + commit + push.
- **`git commit -F .scratch/commit-msg.txt`** — write the message to a file via Write tool, then `git commit -F`.  No `-m`, no heredocs in the terminal.  No `Co-Authored-By: Claude` trailer.
- **Two-repo flow.**  The mono-repo is at `/Users/chuxor/circuitpython/chumicro`; the workspace template repo is at `/Users/chuxor/circuitpython/ChuMicro-Workspace-Template`.  Several workstreams touch both.
- **Branching policy.**  Repo is private — commit directly to `main`; no PRs.
- **All four boards plugged in.**  `devices.yml` registers Lolin S2 (CP+MP) and Pi Pico W (CP+MP).  Hardware-functional tests are runnable via `python scripts/run.py test-workbench-functional` / `test-libraries-functional`.

## How this file works

- One screen, never more.
- Overwritten, not appended.  Older snapshots are recoverable from `git log plans/now.md`.
- Updated in step 4 of `task-checkpoint`.

If you're an agent picking up cold: read this, then `git --no-pager log --oneline -20`, then `plans/next-up.md` if you need the queue.
