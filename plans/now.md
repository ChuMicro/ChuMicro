# Now

**30-second brain snapshot.** Refreshed every `task-checkpoint`. If this file is stale, that means the last session ended without checkpointing — fall back to `git log -10` and `plans/next-up.md`.

This is the front door. Everything else is deeper read.

---

- **Phase:** **chumicro-websockets — leanness pass underway** per `plans/workstreams/websockets-cleanup.md`.  v0.6.x ships 3,628 LOC deployed (vs chumicro-mqtt 1,842) — too fat for embedded targets.  Seven independent slices ranked smallest-blast-radius first: A (FrameParser per-byte→per-chunk), C (slim `__init__`), D (slim `CaseInsensitiveDict`), B (namespace classes→constants), F (compact docstrings + dead defensive code), E (merge handshake parsers), G (shared `_session.py`).  Each slice ships its own version bump + green preflight + commit.
- **Last shipped:** Slice E — extracted `_HandshakeLineParser` base for both handshake parsers; `HandshakeResponseParser` + `HandshakeRequestParser` now subclass it, each owning only their first-line parser + `_finalize` validation.  Shared `_validate_upgrade_headers(role_label)` + `_commit_done()` helpers consolidate the two-header common validation + DONE transition.  Deployed src 3,290 → 3,208 LOC (net −82 since slice F).  v0.8.0 (minor bump — internal refactor; FYI to consumers reaching into `_wire`).
- **In flight:** Slice G — extract shared `_session.py` between WebSocketClient + Connection (~600 LOC dedup; biggest win, biggest test churn).
- **Blocked on:** —
- **Last touched:** libraries/websockets/src/chumicro_websockets/_wire.py, libraries/websockets/VERSION, plans/now.md.

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
