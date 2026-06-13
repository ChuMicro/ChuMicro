# Workstream: Deep code review remediation (2026-06)

Status: **proposed.** Surfaced 2026-06-13 by the full-codebase deep review. Every finding ID below is fully evidenced (file:line, severity, evidence, fix, verification status) in the research artifact: [`plans/reviews/2026-06-13-deep-code-review.md`](../reviews/2026-06-13-deep-code-review.md). User reviewed the report 2026-06-13 ("otherwise looks good") with two carve-outs folded into Phase 4.

Counts: 1 CRITICAL, 11 HIGH, 18 MEDIUM, ~12 LOW, plus 1 ecosystem callout (ECO-1, resolved before this workstream opened — see Phase 9).

## Problem

The review read all 16 device libraries, 5 workbench tools, `support/test_harness`, and `conftest.py` against the project's own invariants (AGENTS.md library rules, `patterns.md`, the relevant ADRs). The trust boundaries that handle hostile input are sound (verified-clean list in the report). The findings cluster into nine bodies of work, ordered below by a blend of severity and blast radius. The single CRITICAL is structural: the runner every library rides on has no per-handler fault isolation.

Each finding's full evidence lives in the report; this file is the execution plan and status tracker. Re-derive any claim marked "agent-reported" against source before fixing it (the report already re-derived every CRITICAL/HIGH marked "verified: yes").

## Scope boundary

Do not re-open these — the report settled them:

- **MQTT-FALSE-1** (negative `bytearray` crash) is unreachable; the two conditions are mutually exclusive. No CRITICAL mqtt phase.
- **HTTP "414 bypass"** was overstated; it is the soft-cap overshoot tracked as HTTP-3 (MEDIUM), not arbitrary-length DoS.

Fold these into existing `next-up.md` items rather than duplicating:

- mqtt `_tx_queue` list -> deque item already tracks the PUBACK-backpressure angle; MQTT-2 adds the recv-N-vs-send-1 drop case.
- `/audit-embedded chumicro_runner.core` + `chumicro_websockets` items are fed by RUN-1, WS-1, WS-2, DEP-4.
- websockets oversize-frame on Lolin S2 relates to WS-1.
- Performance + resource benchmarking infrastructure is the home for validating WS-1 / WS-2 / REQ-1 / MQTT-3 bench claims.
- Restore audit-trimmed comment facts overlaps the Phase 8 LOW cluster.

## Implementation phases

### Phase 1 — Runner fault isolation + tick correctness

**Shipped 2026-06-13 (runner 0.7.0). Real-board bake still pending (orchestration class).** RUN-1 flipped the runner's fault contract from propagate to isolate-and-count: the propagation behavior was deliberately tested (three tests + a "future iteration may swallow" comment), so this was a contract change confirmed by the user's 2026-06-13 fault-model decision (isolate + optional `on_handler_error` hook), not just a bug fix.

Highest priority. Bench on a real board after the fix (orchestration bug class). Confirm against Decision 0080 that tick fault-propagation isn't an intended contract; the `EventBus` / `Logger` precedent says it isn't.

- **RUN-1** (CRITICAL, `runner/core.py:420-426`) — wrap the handler fire in `try/except Exception` (let `KeyboardInterrupt`/`SystemExit`/`GeneratorExit` propagate), route failures to a counter or injected error hook, move `pending.clear()` into `finally` so a raised handler can't leave stale pending entries that re-fire. *verified.*
- **RUN-2** (MEDIUM, `runner/core.py:510` + `_generator.py:209`) — `_dispatch_io_error` iterates `_entries` live while `_mark_done` removes from it, skipping the next entry. Iterate a snapshot or defer removal; correct the `_mark_done` docstring. *agent-reported, re-derive.*
- **RUN-3** (MEDIUM, `runner/generators.py:142`) — `connect()` feeds `connector.tick(0)` a hardcoded `now_ms`. Capture `now_ms = yield connector` and thread it, or document that `connect` passes 0 deliberately. *agent-reported, re-derive.*

### Phase 2 — Test/lint infrastructure integrity

Restores trust in green preflights; mostly CPython-side and well-testable.

- **TEST-1** (HIGH, `pytest-device/result_parser.py:109` + `collection.py:551`) — reconcile the device `SUMMARY total=/failed=` against per-test lines in `_require_batch_result`; `pytest.fail` on mismatch. *agent-reported, confirm.*
- **TEST-2** (HIGH, `checks/rules/chu009_chu010.py:128`) — CHU010 `_function_has_assertion` walks into nested closures; an assert in an unfired callback passes the lint. Walk own control flow only, mirroring `_ifs_in_scope`. *verified.*
- **TEST-3** (HIGH, `checks/rules/chu009_chu010.py:201-213`) — CHU009 never inspects `else:` bodies, so `if HW: assert; else: return` is an unflagged silent pass. Also check `node.orelse`. *verified.*
- **TEST-4** (HIGH, `workspace/boot_shim.py:159` + `cli/deploy.py`) — no mechanized guard blocks deploying an entrypoint with a reachable `microcontroller.reset()`/`machine.reset()`; AGENTS.md bans it in prose only. Add an AST scan in the walker or beside `project_app_exports_async_run`. *verified (grep).*
- **TEST-5** (HIGH, `test_harness/runner.py:202-207`) — `run_module` returns exit 0 on zero discovered tests. Adopt TEST-1's reconciliation; consider `return 1` when `total == 0` and no name filter. *agent-reported, confirm.*
- **TEST-6** (MEDIUM, `conftest.py:119` + `pytest-device/collection.py:828`) — functional-test deselection keys on the substring `"functional_tests"`, not a structural check. Use `_is_library_functional_test(Path(item.fspath))`. *agent-reported, re-derive.*
- **TEST-7** (MEDIUM, `checks/rules/chu009_chu010.py:216-220`) — CHU009 by design never flags a final-statement bare `return`/`pass`; the asymmetry is undocumented. Document the carve-out, or flag a trailing bare return when no assertion precedes it. *verified.*

### Phase 3 — HTTP/WS security + parser hardening

Security-facing.

- **HTTP-1** (HIGH, `http_server/server.py:433`) — response headers emitted without CRLF validation -> handler-reflected response splitting. Reuse the client's `_reject_control_chars` over each response header name/value + reason in `encode_response`. *verified.*
- **HTTP-3** (MEDIUM, `http_server/_wire.py:527-541`) — request-line 414 cap soft by up to one recv chunk. After `crlf_index >= 0`, reject when `crlf_index > max_request_line_bytes` before slicing. *verified.*
- **MSG-1** (HIGH, `msgpack/_pure.py:226,233,247-288` vs docstring `:355-377`) — truncated multi-byte headers raise `IndexError`/`struct.error`, not the documented `ValueError`; given RUN-1, an uncaught parser exception in a tick kills the reactor. Catch and re-raise as `ValueError(_MALFORMED)`, or bounds-check header width before each read. *verified.*

### Phase 4 — Tick-budget / blocking honesty

Several are "document the compromise"; a few are real fixes. Pairs with the tracked benchmarking-infra item.

**User guidance 2026-06-13 on SOCK-1 + WIFI-1: both are known; a resolution likely compromises ease of use. Tread carefully. Prefer documenting the blocking honestly over a behavior change that regresses the connect ergonomics, unless the non-blocking path is clearly free.**

- **SOCK-1** (HIGH, `sockets/_adapters/cpython.py:104`, `mp.py:577`, `cp.py:411`) — connector `AWAITING_DNS` tick calls blocking `getaddrinfo` with no disclosure, unlike the TCP/TLS phases. Document the DNS-phase blocking in the connector docstrings, or use a non-blocking resolver where the platform supports it. *verified. Tread carefully (ease-of-use).*
- **WIFI-1** (HIGH, `wifi/_adapters/cp.py:83`) — CP `radio.connect(timeout=...)` blocks the runner up to 15 s inside `handle()`. Document the CP constraint at the service/adapter-base level, and/or clamp the CP timeout to a per-tick budget and re-arm across ticks. *agent-reported, high confidence. Tread carefully (ease-of-use).*
- **NTP-1** (HIGH, `ntp/core.py:320`) — would-block handling catches only `EAGAIN`, not `EWOULDBLOCK`; macOS-CPython errno 35 permanently fails the exchange. `FakeUDPSocket` pins to `EAGAIN`, hiding it. `if recv_error.errno in (errno.EAGAIN, errno.EWOULDBLOCK):`. *agent-reported, pattern confirmed.*
- **REQ-1** (MEDIUM, `requests/client.py:497,884`; `http_server/server.py:252,314`) — `recv_budget_per_tick > 512` spins up to `budget/512` recv iterations per `handle()`, breaking the tick-latency bound. Size scratch to a documented hard cap, or clamp the loop to 512 and document throughput as `min(budget, 512)`. *agent-reported, high confidence.*
- **WS-1** (MEDIUM, `websockets/_wire.py:939`) — masked-payload unmask is a per-byte Python loop plus a `range(take)` iterator alloc per feed in the server inbound hot path. Drop the `range()` (manual `while` index), keep `recv_budget_per_tick` small; bench on Pico W under a masked flood. *agent-reported, re-derive + bench.*

### Phase 5 — Hot-path allocation sweep

Validate each with the bench loop (`gc.mem_alloc()` bracketed by `gc.disable()`), not static review.

- **WS-2** (MEDIUM, `websockets/_session.py:623`; mirrors `requests/client.py:872`, `http_server/server.py:395`) — send-path slices / per-iteration `memoryview(...)` allocate on the backpressured send loop. Cache a `memoryview` per outbound buffer and slice the view. *agent-reported, re-derive + bench.*
- **MQTT-1** (HIGH, `mqtt/client.py:695`) — callback-bearing QoS-0 publish enqueues packet + marker, each passing the per-call `len >= max` check, so a burst reaches `2x max_tx_queue_size` payload-retaining entries. Reserve two slots in a single capacity check, or document the marker payload cost. *agent-reported, medium confidence.*
- **MQTT-2** (MEDIUM, `mqtt/client.py:1340,1356`) — inbound QoS-1 dispatch is N-per-tick while tx drains one-per-tick; at deque `maxlen`, `appendleft` drops a queued PINGREQ/DUP/PUBACK silently. Bound inbound dispatch toward drain rate, or fault to FAILED at `maxlen` instead of dropping. Folds into the tracked list->deque item. *agent-reported, medium confidence.*
- **MQTT-3** (MEDIUM, `mqtt/client.py:1509-1525`) — `_check_deadlines` can burst N DUP retransmits in one tick, each a full-packet `bytearray` copy. Cap retransmits per tick; store a DUP-flagged copy once on `InFlightPublish`. *agent-reported, medium confidence.*
- **LOG-1** (HIGH, `logging/core.py:112-140`) — the API takes a pre-built string with no deferred `%`-args path, forcing eager f-string alloc before the level check. Add optional `*args`, interpolate `message % args` after the `level < self.level` early-return. *agent-reported, high confidence.*
- **CFG-1** (MEDIUM, `kvstore/core.py:274`) — `bytes_used` re-encodes the whole dict per read. Document "read sparingly", or memoize against a dirty flag. Not a tick path. *agent-reported, medium confidence.*

### Phase 6 — Cross-runtime contract divergence

The fake-hides-the-gap class; needs real-board bakes.

- **SOCK-2** (MEDIUM, `sockets/_adapters/mp.py:597` vs `:366`) — MP TLS connector hands `wrap_socket` a non-blocking socket while documenting "blocks until handshake"; the listener path sets blocking first. `setblocking(True)` before `wrap_socket`, restore after; validate with a real-board TLS connector bake. *agent-reported, needs bake.*
- **SOCK-3** (MEDIUM, `sockets/_adapters/cp.py:161`) — CP UDP `recvfrom_into` raises `OSError(EAGAIN)` on empty; `FakeUDPSocket` returns `(0, addr)`. Make the UDP fake raise to match, or document the divergence loudly. *agent-reported, re-derive.*
- **WIFI-2** (MEDIUM, `wifi/_adapters/mp.py:164`) — `connect_timeout_ms` is dead config on MP (CP-only). Document as CP-only, or enforce on MP by tracking attempt start. *agent-reported, high confidence.*
- **SOCK-4** (MEDIUM, `sockets/__init__.py:47-59`) — `tcp_client_connector` / `tls_client_connector` absent from `__all__` and the module Public-API docstring, so `check-api` under-reports. Add both (alphabetized) + the docstring block. *verified (grep).*
- **DEP-2** (MEDIUM, `deploy/micropython_transport.py:263,573`) — `_decode_exec_result` / `execute` assume a 2-tuple from mpremote; a 1- or 3-tuple raises raw. Guard the unpack on `len(result)`. *agent-reported, medium confidence.*

### Phase 7 — Workbench robustness

- **DEP-1** (HIGH, `deploy/micropython_transport.py:1338`) — `_run_mpremote` has no subprocess timeout; a wedged board hangs deploy forever (the CP path wraps with `_run_subprocess_with_timeout`). Add `timeout=`, catch `TimeoutExpired`, raise `MicropythonTransportError` with wedge guidance for `classify_deploy_failure`. *agent-reported, high confidence.*
- **DEP-3** (MEDIUM, `deploy/circuitpython_transport.py:548,565`) — `_verify_drive_for_board` returns unverified `candidates[0]` when the probe yields no identity -> wrong-board `rsync --delete` wipe on multi-board hosts. Scan candidates for a UID/machine match, or refuse when >1 `CIRCUITPY*` volume is mounted. *agent-reported, medium confidence (single-board hosts unaffected).*
- **DEP-4** (MEDIUM, `deploy/circuitpython_transport.py` + `micropython_transport.py`) — ~3.4k lines of staging/umount/exec-classify logic + device-side scripts duplicated across both transports. Extract `_drop_active_mount()` + `_exec_or_classify()`; hoist device scripts to a shared `_device_scripts.py`. Behavior-preserving. *agent-reported, high confidence.*

### Phase 8 — Comment/doc cleanup

One pass over the LOW cluster (full list in the report's LOW section): SOCK-L1, SOCK-L2, NTP-L1, CFG-L1, CFG-L2, HTTP-L1, MQTT-L1, MQTT-L2 (verified clean), WS-L1, WS-L2, TIME-L1, DEP-L1, DEP-L2. Each is a confirmed prose-vs-code drift or a minor nit; none changes behavior. Merge with the tracked "restore audit-trimmed comment facts" item so one pass covers both. TIME-L1 (Heartbeat silent never-fire above ~74.6 h) and MQTT-L1 (`on_oversized` topic=None `AttributeError`) carry small behavior risk despite living here.

### Phase 9 — Ecosystem decision (RESOLVED)

ECO-1 reported the AGENTS.md-referenced project skills missing from `.github/skills/`. As of 2026-06-13 they are restored and committed (task-checkpoint, git-commit, new-library, new-decision, audit-embedded/-comments/-docs/-skill/-library, `_shared/` all present and tracked), and the downloaded marketplace skills coexist alongside them. Residual: grep `patterns.md` / `next-up.md` / AGENTS.md for any skill reference that still does not resolve, and confirm none remains dangling. Close the phase once that grep is clean.

## Validation history

- 2026-06-13 — Workstream opened from the deep review report. ECO-1 confirmed resolved (skills present + tracked, working tree clean). No code phases shipped yet.
- 2026-06-13 — Phase 1 shipped (runner 0.7.0). RUN-1: `tick()` isolates a faulting handler (catch `Exception`, count in `handler_errors`, report to an optional `on_handler_error(handle, exception)` hook) and clears `_pending` in `finally`; `KeyboardInterrupt`/`SystemExit`/`GeneratorExit` still propagate. RUN-2: documented the single-dispatch-then-return safety at `_dispatch_io_error` and trimmed the rule-violating `_mark_done` docstring. RUN-3: `connect()` threads `now_ms` into `connector.tick()` instead of literal `0`. 160 runner unit tests green, full preflight green. Real-board bake (Pico W, orchestration class) still pending.
