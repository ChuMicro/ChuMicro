# Now

**30-second brain snapshot.** Refreshed every `task-checkpoint`. If this file is stale, that means the last session ended without checkpointing — fall back to `git log -10` and `plans/next-up.md`.

This is the front door. Everything else is deeper read.

---

- **Phase:** **chumicro-websockets — Decision 0045 + slice 1 (wire format) shipped.**  New library `libraries/websockets/` covering both `WebSocketClient` and `WebSocketServer` per Decision 0045 (RFC 6455, runner-shaped per Decision 0014, hard-dep + factory-helper-in-own-submodule per Decision 0042 Class 1, single library because ~80% of the wire code is shared between roles).  Slice 1 ships the bytes-on-the-wire layer — exception hierarchy, opcode/close-code constants, `WebSocketState`, `CaseInsensitiveDict`, URL parser, `make_websocket_key` + `derive_accept_key` (RFC §4.2.2 worked example verified), client + server handshake encoders, streaming `HandshakeResponseParser` / `HandshakeRequestParser`, streaming `FrameParser` (7/16/64-bit length, MASK, RSV rejection, control-frame size limit, fragmentation, oversize-at-length-byte-stage), `encode_frame` (masked/unmasked), close-payload codec, `validate_text_payload` UTF-8 enforcement.  135 tests, 99% line coverage.
- **Last shipped:** `c585d5c` (slice 1 wire), `fbe483f` (Decision 0045 ADR).
- **In flight:** Slice 2 — `WebSocketClient` (state machine + `connect`/`send_text`/`send_binary`/`close` + auto-pong + handshake/close timeouts, FakeConnection-driven tests).
- **Blocked on:** —
- **Last touched:** plans/decisions/0045-chumicro-websockets.md, libraries/websockets/{VERSION,README.md,pyproject.toml,docs/,examples/quickstart.py,src/chumicro_websockets/{__init__,_wire,testing}.py,tests/test_websockets.py}, IDE configs (.idea/chumicro.iml, .vscode/settings.json, pyrightconfig.json).

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
