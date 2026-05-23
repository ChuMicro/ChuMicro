# Workstream: chumicro_mqtt + chumicro_runner cooperative-tick convergence

Status: **proposed.**  Surfaced 2026-05-23 during the Pi Pico W CP TLS bake investigation; divergence inventory expanded 2026-05-23 from an end-to-end read of the reference impl against `chumicro_mqtt.client`, `_wire.py`, and `chumicro_runner.core`.

## Problem

`chumicro_mqtt` and `chumicro_runner` diverge from the cooperative-tick discipline that a proven reference implementation has run in production with multi-week uptimes.  Reference: `~/circuitpython/pythonProject3/basefilesystem/lib/basefs/mqtt_client.py`.  The reference is a monolithic `loop()` (line 476-558) called by the application directly; chumicro splits the equivalent work between `Runner.tick` / `Runner.wait` (dispatch + idle) and `MQTTClient.handle` (per-tick service work).  The split is itself a runner-pattern design choice (Decision 0080) — convergence is not "make chumicro look like the reference," it's "fix the resilience gaps the reference's monolithic loop happens to plug."

## Architecture-level divergences (the bone structure)

Three divergences are not bugs *per se* but shape every concrete defect below.  Worth surfacing first so the punch-list reads in context.

### A. Loop ordering: deadlines first vs deadlines downstream of I/O

Reference `mqtt_client.py:484-557`: capture `now_ms`, check `_waiting_state` timeout (lines 487-500), check `_waiting_to_send` timeout (lines 503-506), maybe queue PING (lines 509-513), set POLLOUT interest if queue non-empty, **then** ipoll + per-event I/O, **then** flip mask back, **then** process buffer.  Deadlines fire *before* any socket call — a wedged recv can't block timeout detection.

Chumicro `client.py:872-876`: `_drain_tx_queue → _read_inbound → _check_deadlines → _check_keepalive → _drain_tx_queue`.  Reads happen before deadline checks, so a stuck recv defers timeout detection by one tick at least (and possibly forever, if the recv blocks).  This is the reference's headline ordering guarantee — chumicro inverts it.

### B. Per-event readiness vs aggregate "did anything wake us"

Reference `mqtt_client.py:524-545`: `for fd, event in ipoll(0):` then explicit `POLLERR` / `POLLHUP` / `POLLIN` / `POLLOUT` branches.  Errors disconnect, reads dispatch, writes drain — each driven by the actual event the kernel surfaced.

Chumicro `runner/core.py:386-387`: `for _ in self._poller.ipoll(timeout_ms): pass` — the per-event iterator is consumed for its side-effect of waking but the events themselves are thrown away.  POLLERR / POLLHUP are not surfaced anywhere, and the runner has no API to surface them to services even if it tried.  Services blindly call `recv_into` / `send` on every tick and rely on EAGAIN to back off.

### C. One chunk per tick vs budget-driven inner loops

Reference `mqtt_client.py:651-672` and `607-626`: `_read_socket` reads once into the 256-byte buffer and returns; `_send_from_queue` pops one packet, sends one packet, returns.  One recv per tick, one packet send per tick.

Chumicro `client.py:1043-1063` (`_read_inbound`): `while consumed < budget:` — loops up to 1024 bytes per tick, recv'ing repeatedly.  Chumicro `client.py:977-994` (`_drain_tx_queue`): `while self._tx_queue:` — pops and sends until queue empty or block.  Both can hold the runner on one service for many ms while LED / button / LCD / other services starve.  The `recv_budget_per_tick` is a partial mitigation but the *shape* is still "drain until you can't" rather than "one per tick."

## Concrete defects (severity-tagged)

Each row is a concrete code-level defect with reference behaviour, chumicro behaviour, and severity.  Severity reflects what *breaks* if the defect is not fixed.

### HIGH — resilience guarantees broken

| Reference behaviour | Chumicro defect | File:line |
|---|---|---|
| Deadline / ack-timeout checks **first**, before any socket I/O.  `mqtt_client.py:487-506`. | `handle()` runs `drain → read → check_deadlines → check_keepalive → drain`.  Deadline check is downstream of read; a stuck recv blocks the timeout that would have caught the hung connection. | `client.py:872-876` |
| `recv_into() == 0` ⇒ peer closed ⇒ `_disconnect_and_raise("Broker closed connection.")` ⇒ caller reconnects.  `mqtt_client.py:668-669`. | `_read_inbound` silently `break`s the loop on `got == 0`, leaves `state` as `CONNECTED`.  Self-heal never fires for a clean TCP FIN — the only way out is a deadline expiring (which itself is blocked by defect above). | `client.py:1060-1061` |
| `POLLERR` / `POLLHUP` → `_disconnect_and_raise`.  `mqtt_client.py:528-531`. | Runner's `wait()` discards the event iterator entirely.  Error / hangup events are ignored, and per-event readiness info isn't surfaced to services at all. | `runner/core.py:386-387` |
| Send timeout (`_waiting_to_send_timeout`): if `_tx_queue` non-empty and no POLLOUT for `timeout` ms ⇒ `_disconnect_and_raise("Timeout waiting to send packet.")`.  `mqtt_client.py:503-506, 519, 545, 551`. | No equivalent.  A socket that never becomes writable (NAT silent-drop, TLS half-closed write) leaves `_tx_queue` growing until `MQTTBackpressureError` from `_enqueue_user_tx` — the *publisher* sees the error, the *client* never transitions to FAILED, self-heal never fires. | (missing — `client.py` has no `_waiting_to_send_timeout` analog) |

### MEDIUM — behaviour differs in ways that interact with the runner contract

| Reference behaviour | Chumicro divergence | File:line |
|---|---|---|
| Receive first within a single loop iteration: POLLIN handling appears before POLLOUT in the per-event branch order (`mqtt_client.py:532-545`).  Per the user's confirmed design call, this lets PUBACKs free in_flight slots before the next batch of publishes lands. | `handle()` drains TX first (`_drain_tx_queue` at line 872), then reads (line 873).  Send-then-recv. | `client.py:872-876` |
| Send suppression while busy: `_send_from_queue` only fires when `not _waiting_state and not _partial_state and _rx_buffer_length == 0` (`mqtt_client.py:537-541`).  Ensures the inbound packet is fully processed before new outbound bytes go on the wire. | No equivalent.  Chumicro sends whenever `_tx_queue` is non-empty; an arriving inbound publish doesn't suppress outbound sends mid-tick. | (architecture — no single line) |
| `_packet_count_that_must_send` discipline: when a packet partial-sends, increment a counter; while > 0, suppress PINGREQ injection (`mqtt_client.py:510, 615-617, 646-648`).  Preserves wire-ordering invariant that the remainder of a partial packet lands before the next discretionary packet. | `_partial_send = (packet, offset)` is stored (`client.py:407`) and resumed in `_drain_tx_queue` (`client.py:967-975`) but the path is `pragma: no cover` — never exercised in tests.  No PING-suppression discipline.  Wire ordering relies on `_drain_tx_queue` running the partial-resume *before* anything else `_check_keepalive` appended — which it does today, but the invariant isn't named or tested. | `client.py:967-975, 1253-1270` |
| `clean_disconnect`: poll-waits up to 150 ms for POLLOUT, sends DISCONNECT, then closes.  `disconnect` (no DISCONNECT, just close) is a separate method.  `mqtt_client.py:308-338`. | Single `disconnect()` method tries best-effort `_send_raw(PACKET_DISCONNECT)` then closes; if socket isn't writable, the DISCONNECT is silently dropped.  No way for the caller to ask for "graceful only" vs "close now." | `client.py:489-505` |
| Single 256-byte RX buffer + partial-state machine for >256-byte messages.  Predictable RAM footprint.  `mqtt_client.py:69-72, 856-912`. | Three-tier decoder (steady / intact-with-allocation / oversized-rolling-discard) with read-cursor + lazy compaction.  More sophisticated, but the tier-2 intact path *allocates* `bytearray(payload_length)` per oversized inbound — a 7 KB inbound on a fragmented heap can fail allocation where the reference's partial-state would have survived. | `_wire.py:457-887` |

### LOW — chumicro improvements worth keeping (no defect, listed so future work doesn't regress them)

| Improvement | Reference behaviour | Chumicro |
|---|---|---|
| Multiple concurrent pending responses (SUBSCRIBE + PUBLISH + PING can coexist). | One `_waiting_state` slot only.  `mqtt_client.py:222-225`. | `_pending_responses` list with per-entry deadlines.  `client.py:400, 480-485, 825-832`. |
| Packet-id collision check on allocation. | `_get_unique_id` is a module-level counter wrapping at 6550 with no collision check.  `mqtt_client.py:102-109`. | `_allocate_packet_id` skips ids already in `_in_flight`, raises `OverflowError` if all 65535 slots are taken.  `client.py:937-953`. |
| Pattern-handler split optimization. | Splits both topic and pattern on every inbound match.  `mqtt_client.py:1014-1043`. | Patterns pre-split at `add_pattern_handler` (`client.py:737`); inbound only splits the topic once (`client.py:1081`). |
| Backpressure as explicit exception, not silent drop. | TX queue uses `deque([], DEQUE_MAX_SIZE, 1)` — silently drops oldest on overflow.  `mqtt_client.py:243`. | `_enqueue_user_tx` raises `MQTTBackpressureError` at the user cap; protocol packets bypass.  `client.py:1005-1021`. |
| Topic-too-long handled gracefully. | Treated as programming error: `_disconnect_and_raise("RX buffer full, Programming Error!")`.  `mqtt_client.py:657-660`. | Tier-3 drain with `topic=None`, emits `_OversizedMessage` event.  `_wire.py:745-760`. |

## Other strays / improvements — research pass extended these but more remain

These came up during the read but are not yet diagnosed as defects vs design choices.  Worth a second look when the workstream is picked up for code.

- **`io_wants_*` poll-mask sync timing.**  Runner's `_sync_poll_set` reads `io_wants_read` / `io_wants_write` at the start of `wait` (`runner/core.py:391-444`), which fires after `tick`.  So the mask reflects the state *after* the service drained its queue this tick.  Reference flips the mask twice per loop iteration (before and after I/O, lines 516-518 + 548-551).  Functionally close but the timing differs by one tick — worth tracing whether that costs any spurious POLLOUT wakeups on a steady publisher.

- **`Runner.wait` returns immediately when no deadlines + no sockets** (`runner/core.py:375-376`).  Tight loop with no sleep.  In practice every chumicro_mqtt client registers a socket while connected, but a `FAILED` client returns `None` from `io_socket` (`client.py:783-792`) and from `next_deadline` (`client.py:819`), so the runner spins until the next tick's `_attempt_self_heal` (which is itself rate-limited only by however fast the loop spins).  Should `wait` enforce a minimum sleep, or should chumicro_mqtt expose a self-heal-retry deadline?

- **`_attempt_self_heal` runs synchronously inside `handle()`.**  If `socket_factory()` does anything slow (DNS lookup, TLS handshake), it blocks the entire runner — every other service stalls until the factory returns or raises.  Reference doesn't have self-heal at all (caller's responsibility); chumicro adopts it but doesn't sandbox the cost.

- **`recv_budget_per_tick` doesn't apply to the tier-2 intact drain or tier-3 oversized drain.**  Both go through `fill_buffer` / `advance`, and `_read_inbound` does respect the budget at the recv call (`client.py:1051-1053`).  But the budget is shared across multiple recv calls within one tick.  Worth confirming with a large-inbound bench whether a 7 KB intact-tier message holds the runner for ~7 ticks (each capped at 1024 bytes) and whether that's acceptable latency.

- **No `POLLERR` / `POLLHUP` API even if the runner surfaced them.**  Adding error-event handling needs a new service-side hook (e.g. `service.io_error(now_ms)` or service-side `state = FAILED` setter triggered from the runner) and matching `_POLLERR` / `_POLLHUP` constants in `runner/core.py`.  Decision needed: should the runner classify socket errors, or just wake the service and let it discover the error on the next recv?

- **`disconnect()` is unconditional close + always fires `on_disconnect()`** (`client.py:495-505`).  Even when called against an already-DISCONNECTED client.  Reference's `disconnect` early-returns when already disconnected (`mqtt_client.py:320-321`).  Idempotency: chumicro fires on_disconnect twice if called twice.

- **Will-message resolution.**  Chumicro resolves the will topic at construct (`client.py:368-374`); reference resolves at `will_set` call.  Both work, but chumicro's makes "construct, then later set will" impossible — no public setter.  Decide whether will-after-construct is a supported pattern (and add a setter) or document as construct-only.

- **`on_publish` callback signature.**  Both reference (`mqtt_client.py:266`) and chumicro (`client.py:609-612`) use `on_publish(topic, payload_bytes)` — same signature.  The handoff's "dead ends" notes the bake author initially assumed `(packet_id)` — that was the bake harness author's mistake, not a chumicro defect.  Listed here only so future-me doesn't waste time on a non-issue.

- **PUBACK ordering vs PING injection.**  Reference increments `_packet_count_that_must_send` when queuing a PUBACK reply for an inbound QoS-1 (`mqtt_client.py:810`).  This prevents `loop()` from queueing a PINGREQ between the PUBACK enqueue and its send.  Chumicro `appendleft`s the PUBACK (`client.py:1087, 1103`) and `_check_keepalive` would `append` a PINGREQ — so PUBACK still goes first by virtue of left/right placement.  Same on-wire behaviour, different mechanism.  Confirm before refactoring either side.

## How to verify the convergence

The bake harness (`projects/mqtt_bake_diag/` in workspace-template, gitignored) is the load test.  After fixes, the bake should:

- Publish 1 Hz from `BAKE_START`, no startup lag.
- Hold `1-blocks`, `free`, `max_free_sz`, `floor` steady across all 30s checkpoints.
- Survive a deliberate broker disconnect (kill mosquitto mid-bake) → board detects within `ack_timeout_seconds + ε`, transitions to `FAILED`, self-heal kicks in when broker restarts.
- Survive a NAT-style silent drop (`pfctl block` on the broker IP from the board) → board hits ack-timeout within `ack_timeout_seconds + ε`, transitions to `FAILED`, self-heal on next tick.
- Survive a broker graceful disconnect (`mosquitto_ctrl ... disconnect <client_id>`) → board sees `recv == 0`, transitions to `FAILED`, self-heal succeeds.  This one is the cleanest test of the recv-zero defect specifically.

The reference satisfies all five against multi-week uptime tests.

## Suggested fix sequencing

The defects don't all need to land together.  Suggested order to maximize signal-per-change:

1. **`recv == 0` ⇒ FAILED** — **LANDED** as commit `bb702f64` (2026-05-23).  Required a paired correction to `chumicro_sockets.testing.FakeSocket` (commit `f91374fe`) so the test fake's `recv_into` matches real non-blocking socket semantics (EAGAIN on no-data, 0 only on FIN).  Regression test `test_peer_close_marks_failed` exercises the fix via the new `simulate_peer_close()` method.  Pending bake validation against the broker-graceful-disconnect test from `mqtt-negative-testing-suite.md`.
2. **Reorder `handle()`: deadlines before I/O** — **LANDED** as commit `5fe9182d` (2026-05-23).  New order is `_check_deadlines → _check_keepalive → _read_inbound → _drain_tx_queue`, which also picks up MEDIUM divergence N (recv before send within the tick).  Pending bake validation against NAT silent-drop.
3. **Send timeout (`_waiting_to_send_timeout`)** (HIGH, adds state + an entry in `next_deadline`).  Needs an ADR-level decision on what "no POLLOUT for X seconds" means in the runner contract.
4. **POLLERR / POLLHUP surfacing** (HIGH, cross-library — runner + mqtt).  Needs runner API addition.  ADR scope.
5. **Remaining MEDIUM items: suppress-send-while-busy, one-chunk-per-tick, `_packet_count_that_must_send` discipline** (deeper refactor of `handle()`).  Land after the high-severity fixes have a green bake.
6. **Self-heal cost sandboxing, idempotent `disconnect`, will-after-construct, etc.** (LOW polish).

## What is not in scope

- Decision 0080 (runner-reactor) rewrite.  Convergence happens within the existing ADR scope; if a fix surfaces something that conflicts with 0080, file an ADR addendum or supersession in `plans/decisions/`.
- mqtt_bake_diag harness improvements.  The harness's clock-domain mix bug (now using `chumicro_timing` exclusively) was a separate fix; further harness polish belongs elsewhere.
- Wifi-router cycle / "underlying socket fail" handling.  Open question whether that's a chumicro-mqtt or chumicro-wifi responsibility; routed to `plans/workstreams/mqtt-negative-testing-suite.md` for decision before code.

## Pointers

- Reference: `/Users/chuxor/circuitpython/pythonProject3/basefilesystem/lib/basefs/mqtt_client.py` (1043 lines).
- Current `chumicro_mqtt.client`: `libraries/mqtt/src/chumicro_mqtt/client.py` (1283 lines).
- Current `chumicro_mqtt._wire`: `libraries/mqtt/src/chumicro_mqtt/_wire.py` (889 lines).
- Current `chumicro_runner.core`: `libraries/runner/src/chumicro_runner/core.py` (488 lines).
- Bake harness: `~/circuitpython/ChuMicro-Workspace-Template/projects/mqtt_bake_diag*/`.
- ADR for the runner contract: [`plans/decisions/0080-runner-reactor.md`](../decisions/0080-runner-reactor.md).
- ADR for the runner pattern (constraints on services): [`plans/decisions/0014-runner-pattern.md`](../decisions/0014-runner-pattern.md).
- Paired test workstream: [`plans/workstreams/mqtt-negative-testing-suite.md`](mqtt-negative-testing-suite.md).
