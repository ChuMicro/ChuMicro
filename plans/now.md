# Now

**30-second brain snapshot.** Refreshed every `task-checkpoint`. If this file is stale, that means the last session ended without checkpointing — fall back to `git log -10` and `plans/next-up.md`.

This is the front door. Everything else is deeper read.

---

- **Phase:** **chumicro-deploy MP-staging exclude bug fixed (0.4.3 → 0.4.4).**  Surfaced while validating the new TLS test on hardware: Pi Pico W MP "ran out of flash" looked like a Decision 0015 boundary at first glance, but actually `MicropythonTransport._copy_tree` had no exclude logic — it blindly copied `__pycache__/*.cpython-3*.pyc`, `*.egg-info/`, `.DS_Store`, `*.pyc` straight onto the device.  ~360 KB of wasted flash on the requests stack (out of ~530 KB total deployed) — the actual library source is only ~240 KB.  After the fix the deploy fits cleanly.  Fix mirrors the exclude set already used by `chumicro_deploy.sources.PackageSource.DEFAULT_EXCLUDED` and `flash_drive.rsync` — both of those filter `__pycache__`; the MP staging path was the outlier.  New `_should_exclude_from_stage` helper + `_STAGE_EXCLUDED_NAMES` constant + dedicated regression test (`test_stage_skips_host_only_build_artifacts`).  Also corrects the stale claim in the prior commit (`6595317`) that "Pi Pico W MP can't fit the requests stack" — it can; the previous commit's assertion was a symptom, not a limit.  **Pi Pico W MP TLS still fails** but at runtime this time (`ssl.wrap_socket` OSError ENOMEM during handshake — only ~190 KB MP heap on the rp2 port, mbedTLS + wifi + sockets context doesn't fit), which is a real Decision 0015-class runtime limit.  TLS test docstring updated to document the runtime-vs-flash distinction.
- **Last shipped:** chumicro-deploy 0.4.4 — MP-staging exclude fix (this commit).
- **In flight:** —
- **Blocked on:** —
- **Last touched:** `workbench/deploy/{VERSION, src/chumicro_deploy/micropython_transport.py, tests/test_micropython_transport.py}`; `libraries/requests/functional_tests/test_real_get_tls.py`.

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
