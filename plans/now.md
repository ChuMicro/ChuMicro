# Now

**30-second brain snapshot.** Refreshed every `task-checkpoint`. If this file is stale, that means the last session ended without checkpointing — fall back to `git log -10` and `plans/next-up.md`.

This is the front door. Everything else is deeper read.

---

- **Phase:** **chumicro-websockets — Decision 0045 v0.5.1 shipped (slices 1–6 complete).**  New library `libraries/websockets/` covering both `WebSocketClient` and `WebSocketServer` per Decision 0045 (RFC 6455, runner-shaped per Decision 0014, hard-dep + factory-helper-in-own-submodule per Decision 0042 Class 1).  Six slices: wire layer → client → server → testing fakes + integration → sockets_factory + docs/examples → live-board functional.  267 host-side tests at 95% coverage; live-board functional verified PASS on Lolin S2 (both CP + MP) end-to-end (handshake + bidirectional echoes + close).  Live verification turned up three real cross-runtime bugs the host harness couldn't catch: CP's `hashlib.sha1` is feature-gated off (added pure-Python SHA-1 fallback, FIPS 180-4 verified), CP rejects `del bytearray[start:stop]` (switched to slice-rebind in handshake parsers + FakeConnection.recv_into), and Pi Pico W rp2 can't single-device-loopback (test now skips cleanly on rp2 with a clear printed reason — independent of websockets, the rp2 lwIP self-loopback limit also affects chumicro-http-server).
- **Last shipped:** `b116f06` (slice 6 + cross-runtime fixes), `a2bd336` (slice 5 docs+sockets_factory), `a1a810b` (slice 4 testing+integration), `065dc75` (slice 3 server), `613cc99` (slice 2 client), `c585d5c` (slice 1 wire), `fbe483f` (Decision 0045 ADR).
- **In flight:** idle — chumicro-websockets v0.5.1 is feature-complete per Decision 0045 v1 scope.
- **Blocked on:** Pi Pico W CP live-board verification — the board's USB serial port (`/dev/cu.usbmodem112301`) needs power-cycle to re-enumerate after a chip wedge mid-test.  Test code already skips cleanly on rp2 either way; live confirmation pending hardware reset.
- **Last touched:** plans/decisions/0045-chumicro-websockets.md, libraries/websockets/ (whole tree), IDE configs (.idea/chumicro.iml, .vscode/settings.json, pyrightconfig.json).

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
