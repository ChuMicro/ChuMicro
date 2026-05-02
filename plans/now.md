# Now

**30-second brain snapshot.** Refreshed every `task-checkpoint`. If this file is stale, that means the last session ended without checkpointing — fall back to `git log -10` and `plans/next-up.md`.

This is the front door. Everything else is deeper read.

---

- **Phase:** **Two related plan-cleanup slices closed.**  (1) Retired the four `.scratch/run_{wifi,sockets,requests,http_server}_acceptance.py` host-driven runners — superseded by canonical `libraries/*/functional_tests/test_real_*.py` suites since the unified `chumicro-pytest-device` plugin shipped 2026-04-27.  Salvaged the one genuinely distinct path (pinned-CA HTTPS via `chumicro_sockets.ssl_context_with_ca`) into `libraries/requests/functional_tests/test_real_get_tls.py` — HttpClient + TLS context + RTC seed via `_test_creds.NOW_UTC_TUPLE` injected by the conftest; CA bundle inlined for refresh on Cloudflare rotation.  Deleted the four runners and the four scratch CA-bundle PEMs.  Hardware-validated 4/4 on the boards with adequate flash (Pi Pico W CP flash 6.89 s, Lolin S2 MP flash 5.36 s); Pi Pico W MP flash too full to fit the requests stack — pre-existing Decision 0015 boundary, also affects `test_real_get.py`.  (2) Killed the open "library-self-declared deploy-mode constraints" follow-up + stripped the Pi-Pico-W-CP-needs-flash-mode callout from `libraries/mqtt/README.md`.  The originating constraint table experiment had already been reverted (`f225fe5` → `95e57fc`); the README + recovery-hint stop-gap (`9740f15`) was the remaining "prepared support".  Conclusion: the existing `--deploy-mode flash` flag plus the recovery-layer's generic `INSUFFICIENT_MEMORY` plan are sufficient — no library × board × runtime routing infrastructure needed.
- **Last shipped:** plan/scratch cleanup + chumicro-requests TLS functional test salvage (this commit).
- **In flight:** —
- **Blocked on:** —
- **Last touched:** `libraries/requests/functional_tests/{test_real_get_tls.py (new), conftest.py}`; `libraries/mqtt/README.md`; `plans/next-up.md`; `.scratch/run_*_acceptance.py` + `example_*.pem` (deleted).

---

## What a fresh session should read first

1. This file (`plans/now.md`).
2. `git --no-pager log --oneline -20` — what just shipped, in order.
3. `plans/next-up.md` — queue (`## Now`) + recent done log.
4. `plans/decisions/` — only when proposing structural changes.

## Pick-up candidates (sorted by readiness)

| Candidate | Where | Notes |
|---|---|---|
| Extract shared per-runtime adapter helper | `next-up.md` `## Next` | Now has only **one** remaining ladder consumer (`chumicro_kvstore.core._select_backend`); the wifi unification removed the second.  Low urgency until a third consumer surfaces. |
| Anything else in `## Next` of `next-up.md` | `plans/next-up.md` | Rebrand to ChipPy, OTA workstream (`plans/workstreams/ota.md`), digital I/O library, performance benchmarking infrastructure, etc. |

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
