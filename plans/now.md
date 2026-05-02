# Now

**30-second brain snapshot.** Refreshed every `task-checkpoint`. If this file is stale, that means the last session ended without checkpointing — fall back to `git log -10` and `plans/next-up.md`.

This is the front door. Everything else is deeper read.

---

- **Phase:** **CP-rp2 TLS server officially unsupported.**  Live-reproduced 2026-05-02 on Pi Pico W (CP 10.2.0-rc.0): `wrap_socket(server_side=True) + accept()` raises `OSError(32)` mid-handshake when a real host TLS client connects, AND the failure wedges the CYW43 chip's station-mode state — every subsequent `wifi.radio.connect()` returns `Unknown failure 1` until USB power-cycle (`microcontroller.reset()` doesn't toggle CYW43's WL_REG_ON).  `chumicro_sockets.tls_listening_socket` now refuses CP-rp2 up-front via `UnsupportedSSLConfigError` (detection: `sys.platform.upper().startswith("RP2")` covers both rp2040 + rp2350).  Stale "rp2-port mbedTLS feature-flag gap" framing retired everywhere.  chumicro-sockets 0.2.1 → 0.2.2.
- **Last shipped:** commits `5a51448` (learnings.md correction) + `5316181` (CP-rp2 listen_tls guard + Decision 0041 §8 rewrite + docs sweep).
- **In flight:** idle.
- **Blocked on:** —
- **Last touched:** AGENTS.md, libraries/{http_server,sockets}/docs/guide.md, libraries/http_server/{README.md,src/chumicro_http_server/__init__.py}, libraries/sockets/{VERSION,src/chumicro_sockets/{__init__,_adapters/cp}.py,tests/test_factories.py}, plans/decisions/0041-chumicro-http-server.md, plans/learnings.md.

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
