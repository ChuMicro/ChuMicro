# Now

**30-second brain snapshot.** Refreshed every `task-checkpoint`. If this file is stale, that means the last session ended without checkpointing — fall back to `git log -10` and `plans/next-up.md`.

This is the front door. Everything else is deeper read.

---

- **Phase:** **Library docs audit pass closed.**  Two-commit sweep over the 14 libraries' READMEs + per-library docs/.  Pass 1 (`7ea6491`) fixed AGENTS.md (5 missing libraries added; stale wifi / sockets / mqtt / workspace rows refreshed), corrected the `chumicro-http-server` "TLS server is investigated separately" line that contradicted `plans/learnings.md` (TLS server is verified-working on every runtime/board pair *except* CP-on-rp2), surfaced mqtt 0.1.4's `recv_budget_per_tick` / `max_tx_queue_size` / `MQTTBackpressureError` knobs, and lifted the `chumicro-msgpack` wire-format-compat invariant into the guide.  Pass 2 (`f5e2aa1`) replaced the new-library-scaffolder template fingerprint (61-line stubs with `<!-- GENERATION INSTRUCTIONS -->` blocks intact) on five guides (config, kvstore, wifi, http_server, mqtt), three indexes (http_server, kvstore, mqtt), and one testing helpers page (kvstore) — all derived from the package `__init__.py` exports + module docstrings.  Up next: root README + CONTRIBUTING + workspace-template repo audit.
- **Last shipped:** docs: library audit pass 2 — fill 5 stub guides + 3 stub indexes + kvstore testing (`f5e2aa1`).
- **In flight:** root + CONTRIBUTING + ChuMicro-Workspace-Template audit (research stage; user-requested).
- **Blocked on:** —
- **Last touched:** AGENTS.md, libraries/{config,kvstore,wifi,http_server,mqtt}/docs/, libraries/{http_server,wifi,mqtt,msgpack}/README.md, libraries/http_server/src/chumicro_http_server/__init__.py.

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
