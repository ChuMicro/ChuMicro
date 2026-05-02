# Now

**30-second brain snapshot.** Refreshed every `task-checkpoint`. If this file is stale, that means the last session ended without checkpointing — fall back to `git log -10` and `plans/next-up.md`.

This is the front door. Everything else is deeper read.

---

- **Phase:** **TLS test now pins the root, not the chain — clean 4/4 across all four boards.**  User pushback on commit `b000306`'s "Pi Pico W MP TLS OOMs at runtime" claim turned out to be the same misdiagnosis pattern as the earlier flash-bloat one: I'd pinned the whole 3-cert chain (3.7 KB PEM) when mbedTLS only needs the root that anchors trust.  The redundant intermediate + cross-sign cost extra handshake heap and (worse) the AAA cross-sign's `NotBefore` 2025-08-01 forced RTC seeding the test wouldn't otherwise need.  Switched to pinning just `SSL.com TLS ECC Root CA 2022` (1.3 KB, `NotBefore` 2022-10-21) — Cloudflare's intermediate comes from the server during the handshake, validation still works.  Pi Pico W MP TLS test now PASSES (5.27 s); previously claimed "real Decision 0015 runtime limit" was actually heap pressure from the over-pinned chain.  Lifted the lesson to `plans/learnings.md` "Pin the root, not the chain — embedded TLS clients only need the trust anchor" so the next session doesn't repeat it.  RTC seeding is still needed because the SSL.com root's 2022 `NotBefore` post-dates the embedded ports' 2021-01-01 boot RTC default; documented in the same learnings entry.
- **Last shipped:** chumicro-requests TLS test — single-root CA pin (this commit).
- **In flight:** —
- **Blocked on:** —
- **Last touched:** `libraries/requests/functional_tests/test_real_get_tls.py`; `plans/learnings.md` (new "Pin the root, not the chain" entry).

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
