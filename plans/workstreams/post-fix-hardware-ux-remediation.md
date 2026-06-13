# Workstream: Post-fix hardware + UX remediation (2026-06)

Status: **in progress — opened 2026-06-13.** Phase 0 (coverage gap) done — WS-1 / HTTP-3 / HTTP-1 re-read and verified clean. Phase A (library correctness, L1 + L2) shipped. Phase B (workbench failure handling) next. Full evidence for every finding ID lives in the research artifact: [`plans/reviews/2026-06-13-post-fix-hardware-ux-review.md`](../reviews/2026-06-13-post-fix-hardware-ux-review.md).

Counts: 1 HIGH + 2 MEDIUM library, 1 MEDIUM cross-cutting (docs), 6 HIGH + 2 MEDIUM + 1 LOW workbench.

## Problem

The second review pass (after the deep-code-review remediation Phases 1-9 landed) re-derived the recent fixes against source and found most held — MQTT-1/MQTT-3, WS-2 (both sites), SOCK-2, MSG-1 are verified clean. One regression slipped in (L1), two pre-existing-but-now-sharper interaction bugs surfaced (L2, L3), the connect-blocks-the-reactor substrate limit needs to reach the user guide (H1), and the workbench recovery machinery is bypassed by three of four hardware-touching CLIs (the W-cluster).

Each finding's full evidence lives in the report; this file is the execution plan + status tracker. Re-derive any claim before fixing. The report already re-derived every library finding and hand-verified W6; the rest of the W-cluster is the UX agent's, marked accordingly.

## Scope boundary

- The deep-review remediation already shipped WS-1 (Phase 4) and HTTP-3 (Phase 3). This pass did **not** re-read `websockets/_wire.py` or `http_server/_wire.py` — Phase 0 closes that, verifying the prior fixes held and checking for anything new. It is verification, not re-implementation.
- Verified-clean this pass (do not re-open): MQTT-1 atomic enqueue, MQTT-3 cached DUP bytes, WS-2 memoryview lifetime (websockets + requests), SOCK-2 (the setblocking-on-failure worry is moot — `SocketConnector._fail` closes the socket), MSG-1 exception tuple, the HTTP/WS/MQTT sender-controlled allocation caps.
- SOCK-1 / WIFI-1 stay documented-not-fixed per the 2026-06-13 user guidance (a non-blocking resolution compromises connect ergonomics). H1 extends that documentation stance to MP-TLS + the user guide; it is not a behavior change.

## Implementation phases

### Phase 0 — Close review coverage gap

**Done 2026-06-13 — both files read, prior fixes verified clean, no new actionable findings.**

Five of six library review agents died on a transient API rate limit, so the libraries were read by hand and two parser files went unread. Re-read this pass.

- **GAP-WS1** — `websockets/_wire.py` read. WS-1 hand-indexed unmask (`_wire.py:944-950`) is allocation-free (bytearray indexed-assign, memoryview index, no `range()`) and **correct across feed-chunk boundaries**: it masks with the absolute payload offset `(write_offset + index) & 3`, not a chunk-relative index, which is the subtle part. Length tiers (0 / <126 / len16 / len64), control-frame ≤125 enforcement, and tier-3 oversized drain all correct. *verified clean.*
- **GAP-HTTP3** — `http_server/_wire.py` + `server.py` read. HTTP-3 request-line cap rejects before slicing (`_wire.py:546-550`); body cap rejects >`max_body_bytes` as 413 before any allocation (`:659-668`); headers cap → 431 (`:596-600`); Transfer-Encoding request bodies rejected to block smuggling (`:634-641`). HTTP-1 `_reject_control_chars` (`server.py:419-428`) applied to reason + every response header name/value (`:444-454`). *verified clean.*
- **GAP-OBS-1** (LOW, pre-existing, not actionable) — client-side `make_mask_key`→`os.urandom(4)` (`_wire.py:1106`) runs per outbound frame and per auto-pong inside a tick; AGENTS.md lists MP `os.urandom` as a tick-budget offender, but it is hardware-RNG-backed and fast on rp2/esp32, and RFC 6455 §5.3 requires strong randomness so a PRNG is the wrong fix. Note only; confirm timing if a websocket-client bench is ever run.

### Phase A — Library correctness regressions

Small, isolated, well-testable. L1 is the priority — a crash regression in a library everything logs through.

**Phase A complete 2026-06-13: L1 (logging 0.3.1) + L2 (runner 0.8.0) shipped. L2's behavior change was approved by the user 2026-06-13 — a re-entrant tick now propagates loudly.**

- **L1** (HIGH, `libraries/logging/src/chumicro_logging/core.py:124`) — `Logger.log`'s `message % args` interpolation sat outside the `try/except` that wraps `handler.emit`, so a format/arg mismatch raised into the caller and broke the class's documented "logging never crashes the app" contract. **Shipped (logging 0.3.1):** guarded the interpolation in a `try/except Exception`, rendered a visible fallback `f"{message!r} % {args!r} (log-format error: …)"`, counted it in `handler_errors`; updated both docstrings; test `test_logger_format_mismatch_does_not_crash_the_caller`. *verified.*
- **L2** (MEDIUM, `libraries/runner/src/chumicro_runner/core.py`) — RUN-1's `except Exception` swallowed the re-entrancy guard's `RuntimeError`, so a handler that re-entered `tick()` got a silent `handler_errors` bump instead of a loud crash. **Shipped 2026-06-13 (runner 0.8.0), user-approved.** Re-entering the reactor is framework misuse, categorically different from a service handler raising a domain exception, so it now propagates. Added `ReentrantTickError(RuntimeError)` (exported), the guard raises it, and the dispatch loop re-raises it past the handler-fault isolation while ordinary faults stay isolated unchanged. Rewrote `test_reentrant_tick_from_handler_is_isolated` to `test_reentrant_tick_from_handler_propagates` (asserts it raises, `handler_errors == 0`, and the runner recovers once the offending handler is removed). *verified.*

### Phase B — Workbench failure-handling root cause

One root cause: `deploy` / `install-firmware` / `reset-board` don't catch the exceptions the recovery machinery re-raises (only `deploy-example` does). Fixing catch-and-classify at those sites + a firmware failure-kind enum resolves four findings together.

- **W9** (LOW, `workbench/deploy/src/chumicro_deploy/firmware.py:132-139`) — add a `FirmwareFailureKind` enum + classifier (or a `kind` attribute on `FlashFirmwareError`) so CLIs can route on kind. Do this first; B's other findings catch against it. *agent-reported, re-derive.*
- **W2** (HIGH, `workbench/workspace/src/chumicro_workspace/cli/deploy.py:609-616`) — wrap `deploy_diff` in catch-and-classify like `deploy-example` (`cli/examples.py:449-461`); absorb the re-raise into a clean exit code. *agent-reported, re-derive.*
- **W3** (HIGH, `cli/deploy.py:565-616`) — same catch, placed *inside* the `--all-devices` / `--all-projects` inner loop with `continue`, so one device's failure doesn't abort the rest (its `--help` already promises this). *agent-reported, re-derive.*
- **W4** (HIGH, `workbench/workspace/src/chumicro_workspace/cli/firmware.py:66-74,110-114`) — wrap `flash_fn` and `wipe_filesystem` in catch-and-classify; wire an `on_progress` so a multi-MB flash isn't a silent terminal. *agent-reported, re-derive.*
- **W6** (HIGH, `cli/_common.py:89-105` + `cli/deploy.py:610`) — resolve `--non-interactive` from `sys.stdin.isatty()` centrally (near `main()`) so the documented auto-detect is real on every command, not just `deploy-example`. *hand-verified in the report.*

### Phase C — Workbench coaching copy + heuristics

- **W1** (HIGH, `workbench/.../recovery_plans.py:51-54`) — rewrite the `NO_PYTHON_RUNTIME` plan to the real `install-firmware` surface (`--device`, required `--method uf2|esptool`, URL from devices.yml); drop the nonexistent `--board` / `--address` / `--list-boards`. *agent-reported, re-derive against the live parser.*
- **W5** (HIGH, `micropython_transport.py:1363-1371` + `recovery.py:121-127`) — add a timeout-pattern classification row mapped to a non-retryable kind so a wedged board isn't retried into a ~6-min hang; add a test asserting `classify_deploy_failure(timeout)` is non-retryable. *agent-reported, re-derive.*
- **W7** (MEDIUM, `circuitpython_transport.py:567-586` + `circuitpy_drive.py:105-121`) — list the candidate paths in the refusal (flag empty ones), and count only `boot_out.txt`-bearing mounts toward "ambiguous" so one real board + a stale `CIRCUITPY 1` stops false-refusing. *agent-reported, re-derive.*
- **W8** (MEDIUM, `cli/deploy.py:175-191`) — scan the resolved import-graph file set for `microcontroller.reset()`/`machine.reset()` on boot-shim layouts, not just the entrypoint; or document the limit in the refusal. *agent-reported, re-derive.*

### Phase D — Hardware-reality docs

No behavior change. Make the substrate limits the user trips on visible where they look.

- **H1** (MEDIUM, docs) — user-guide section: MP TLS handshake (`sockets/_adapters/mp.py:612`) and CP wifi connect block the whole cooperative reactor for the round-trip (seconds); what freezes, measured per-board worst-case, guidance to connect before starting time-critical services. Surface on mqtt + requests `connect()`/`from_config` docstrings, not only the sockets adapter. Add the WIFI-2 `connect_timeout_ms`-is-CP-only "what happens on MicroPython" line (read `wifi/` first).
- **L3** (MEDIUM, `libraries/msgpack/src/chumicro_msgpack/_pure.py:318,333` + docstring) — either add an optional `max_items` absolute cap to `unpackb` (defaulted off), or make the trusted-only disclaimer load-bearing with a one-line caveat in the mqtt + requests guides against `unpackb`-ing attacker-controlled payloads.

## Validation history

- 2026-06-13 — Workstream opened from the post-fix review report.
- 2026-06-13 — Phase 0: re-read `websockets/_wire.py` + `http_server/_wire.py` + `server.py`. WS-1, HTTP-3, HTTP-1 verified clean; no new actionable findings (one LOW `os.urandom` note recorded as GAP-OBS-1). No code changed.
- 2026-06-13 — Phase A / L1 shipped (logging 0.3.1): guarded `Logger.log`'s `message % args` so a format mismatch renders a visible fallback + counts `handler_errors` instead of crashing the caller; test added.
- 2026-06-13 — Phase A / L2 shipped (runner 0.8.0), user-approved: re-entrant `tick()` now propagates `ReentrantTickError` past the handler-fault isolation instead of being silently counted; ordinary handler faults stay isolated. Locking test rewritten to assert propagation. Error-path-only change (steady-state tick + allocation unchanged); real-board validation folds into the already-pending RUN-1 runner-tick bake. Phase A complete.
