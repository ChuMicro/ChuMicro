# Workstream: chumicro_mqtt + chumicro_runner cooperative-tick convergence

Status: **landed** (fix-sequencing steps 1–8 shipped and negative-bake-validated
2026-05-23 — see the per-step commits below).  2026-07-04: self-heal cost sandboxing
(step 6's deferred half) landed in mqtt 0.23.0 — connector-driven connect path with an
attempt deadline and backoff-paced retries, see the step-6 entry — and the PUBACK-backlog
interim guard shipped (fault-to-FAILED at the tx hard cap, see the last stray below).
Both bake-validated the same day — see the
2026-07-04 rows in the validation table.  The last open residual — recv-N-vs-send-1
rate convergence, the guard's real fix — **shipped in mqtt 0.24.0** (2026-07-04): each
tick's inbound-QoS-1 PUBACKs coalesce into ONE front-of-queue batch the drain flushes
outside the per-tick packet budget (ack rate tracks dispatch rate; PINGREQ and user
publishes keep the send slot), and the recv is suppressed while a batch is still
unsent, so an unwritable socket throttles the broker through the TCP window instead of
growing our backlog.  The hard-cap guard is demoted to a last-resort backstop
(reachable only when retransmits/replays have exhausted the whole protocol headroom).
Pending hardware bake: a QoS-1 flood scenario.  Several divergence
rows reference surfaces Decision 0099 has since deleted (three-tier decoder → two-tier,
pattern-handler router removed) — those rows are annotated in place.  Surfaced 2026-05-23
during the Pi Pico W CP TLS bake investigation; divergence inventory expanded 2026-05-23
from an end-to-end read of the reference impl against `chumicro_mqtt.client`, `_wire.py`,
and `chumicro_runner.core`.

## Problem

`chumicro_mqtt` and `chumicro_runner` diverge from the cooperative-tick discipline that a previous-generation MQTT reference implementation has run in production with multi-week uptimes.  The reference is a monolithic `loop()` (line 476-558) called by the application directly; chumicro splits the equivalent work between `Runner.tick` / `Runner.wait` (dispatch + idle) and `MQTTClient.handle` (per-tick service work).  The split is itself a runner-pattern design choice (Decision 0080) — convergence is not "make chumicro look like the reference," it's "fix the resilience gaps the reference's monolithic loop happens to plug."

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

*RESOLVED in two steps.*  Step 5 (commit `599a9615`, 2026-05-23) landed one recv + one send per tick.  mqtt 0.24.0 (2026-07-04) closed the residual dispatch-rate gap: the one recv can still surface N complete packets, so the N PUBACKs they owe now coalesce into ONE front-of-queue batch the drain flushes as one extra send outside the per-tick packet budget (at most two sends per tick), and the recv is suppressed while a batch is unsent — inbound dispatch can no longer outrun the ack drain, and `recv_budget_per_tick` becomes the single inbound pacing lever (bytes per tick, hence packets dispatched per tick, hence batch size).

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
| Single 256-byte RX buffer + partial-state machine for >256-byte messages.  Predictable RAM footprint.  `mqtt_client.py:69-72, 856-912`. | RESOLVED by Decision 0099 (2026-07-03): the tier-2 intact path — whose per-message `bytearray(payload_length)` allocation was the concern here — is deleted; the decoder is now two-tier (steady / oversized-rolling-discard) with no per-message allocation. | `_wire.py` (two-tier) |

### LOW — chumicro improvements worth keeping (no defect, listed so future work doesn't regress them)

| Improvement | Reference behaviour | Chumicro |
|---|---|---|
| Multiple concurrent pending responses (SUBSCRIBE + PUBLISH + PING can coexist). | One `_waiting_state` slot only.  `mqtt_client.py:222-225`. | `_pending_responses` list with per-entry deadlines.  `client.py:400, 480-485, 825-832`. |
| Packet-id collision check on allocation. | `_get_unique_id` is a module-level counter wrapping at 6550 with no collision check.  `mqtt_client.py:102-109`. | `_allocate_packet_id` skips ids already in `_in_flight`, raises `OverflowError` if all 65535 slots are taken.  `client.py:937-953`. |
| Pattern-handler split optimization. | (Row obsolete: Decision 0099 deleted the pattern-handler router entirely — `on_message` + `next_message()` + public `topic_matches()` cover its use.) | — |
| Backpressure as explicit exception, not silent drop. | TX queue uses `deque([], DEQUE_MAX_SIZE, 1)` — silently drops oldest on overflow.  `mqtt_client.py:243`. | `_enqueue_user_tx` raises `MQTTBackpressureError` at the user cap; protocol packets bypass.  `client.py:1005-1021`. |
| Topic-too-long handled gracefully. | Treated as programming error: `_disconnect_and_raise("RX buffer full, Programming Error!")`.  `mqtt_client.py:657-660`. | Tier-3 drain with `topic=None`, emits `_OversizedMessage` event.  `_wire.py:745-760`. |

## Other strays / improvements — research pass extended these but more remain

These came up during the read but are not yet diagnosed as defects vs design choices.  Worth a second look when the workstream is picked up for code.

- **Poll-mask sync timing** (the paired `io_wants_*` bools became the `io_interest(now_ms)` bitmask in Decision 0097; the timing question survives the rename).  Runner's `_sync_poll_set` reads the interest at the start of `wait`, which fires after `tick`.  So the mask reflects the state *after* the service drained its queue this tick.  Reference flips the mask twice per loop iteration (before and after I/O, lines 516-518 + 548-551).  Functionally close but the timing differs by one tick — worth tracing whether that costs any spurious POLLOUT wakeups on a steady publisher.

- **`Runner.wait` returns immediately when no deadlines + no sockets** (`runner/core.py:375-376`).  Tight loop with no sleep.  In practice every chumicro_mqtt client registers a socket while connected, but a `FAILED` client returns `None` from `io_socket` (`client.py:783-792`) and from `next_deadline` (`client.py:819`), so the runner spins until the next tick's `_attempt_self_heal` (which is itself rate-limited only by however fast the loop spins).  Should `wait` enforce a minimum sleep, or should chumicro_mqtt expose a self-heal-retry deadline?  *Resolved on the mqtt side (mqtt 0.18.0 backoff + 0.23.0): FAILED-with-self-heal now surfaces the backoff retry deadline through `next_deadline` — or `now_ms` before any backoff is armed — so the runner parks by it instead of spinning.*

- **`_attempt_self_heal` runs synchronously inside `handle()`.**  If `socket_factory()` does anything slow (DNS lookup, TLS handshake), it blocks the entire runner — every other service stalls until the factory returns or raises.  Reference doesn't have self-heal at all (caller's responsibility); chumicro adopts it but doesn't sandbox the cost.  *LANDED 2026-07-04 (mqtt 0.23.0) — see the step-6 entry: self-heal builds a Decision-0098 connector and ticks it across `handle()` calls under a per-attempt deadline.*

- **`recv_budget_per_tick` doesn't apply to the tier-2 intact drain or tier-3 oversized drain.**  Both go through `fill_buffer` / `advance`, and `_read_inbound` does respect the budget at the recv call (`client.py:1051-1053`).  But the budget is shared across multiple recv calls within one tick.  Worth confirming with a large-inbound bench whether a 7 KB intact-tier message holds the runner for ~7 ticks (each capped at 1024 bytes) and whether that's acceptable latency.

- **No `POLLERR` / `POLLHUP` API even if the runner surfaced them.**  Adding error-event handling needs a new service-side hook (e.g. `service.io_error(now_ms)` or service-side `state = FAILED` setter triggered from the runner) and matching `_POLLERR` / `_POLLHUP` constants in `runner/core.py`.  Decision needed: should the runner classify socket errors, or just wake the service and let it discover the error on the next recv?

- **`disconnect()` is unconditional close + always fires `on_disconnect()`** (`client.py:495-505`).  Even when called against an already-DISCONNECTED client.  Reference's `disconnect` early-returns when already disconnected (`mqtt_client.py:320-321`).  Idempotency: chumicro fires on_disconnect twice if called twice.

- **Will-message resolution.**  Chumicro resolves the will topic at construct (`client.py:368-374`); reference resolves at `will_set` call.  Both work, but chumicro's makes "construct, then later set will" impossible — no public setter.  Decide whether will-after-construct is a supported pattern (and add a setter) or document as construct-only.

- **`on_publish` callback signature.**  Both reference (`mqtt_client.py:266`) and chumicro (`client.py:609-612`) use `on_publish(topic, payload_bytes)` — same signature.  The handoff's "dead ends" notes the bake author initially assumed `(packet_id)` — that was the bake harness author's mistake, not a chumicro defect.  Listed here only so future-me doesn't waste time on a non-issue.

- **PUBACK ordering vs PING injection.**  Reference increments `_packet_count_that_must_send` when queuing a PUBACK reply for an inbound QoS-1 (`mqtt_client.py:810`).  This prevents `loop()` from queueing a PINGREQ between the PUBACK enqueue and its send.  Chumicro `appendleft`s the PUBACK (`client.py:1087, 1103`) and `_check_keepalive` would `append` a PINGREQ — so PUBACK still goes first by virtue of left/right placement.  Same on-wire behaviour, different mechanism.  Confirm before refactoring either side.
- **PUBACK backlog can drop protocol packets at the deque cap (deep-review MQTT-2, folded in 2026-06-13).**  `_handle_inbound_publish` / `_handle_oversized` `appendleft` a PUBACK per inbound QoS-1, but the TX drain sends one packet per tick.  A broker pushing many small QoS-1 PUBLISHes faster than that drain grows the PUBACK backlog against the bounded `_tx_queue` (`maxlen = max_tx_queue_size + 64`); at `maxlen`, `appendleft` silently drops the far-end entry — losing a queued PINGREQ, DUP retransmit, or PUBACK.  **Interim guard SHIPPED 2026-07-04 (mqtt 0.23.0):** the PUBACK flush in `_read_inbound` detects the queue at the hard cap before the protocol `appendleft` and faults to FAILED with a "PUBACK backlog overflowed the tx queue hard cap" `last_error` instead of dropping — self-heal rebuilds cleanly and the broker redelivers whatever was never acked, so QoS-1 correctness survives the fault.  **REAL FIX SHIPPED 2026-07-04 (mqtt 0.24.0):** the tick's PUBACKs coalesce into ONE front-of-queue batch (receipt order preserved inside the batch, one queue entry per tick regardless of inbound rate); `_drain_tx_queue` flushes the batch without consuming its one-packet-per-tick budget, so acks leave in the tick they were incurred and PINGREQ / user publishes never starve behind them; and `_read_inbound` skips its recv while a batch (or a partial send) is still unsent — unread bytes stay in the kernel buffer, the TCP window closes, and the broker throttles at its end (which also structurally pins cross-tick PUBACK receipt order: a second batch can't queue in front of an unsent first).  The guard stays as a last-resort backstop, now reachable only when DUP retransmits / subscription replays have already consumed the entire 64-slot protocol headroom.  Regression tests: `test_client_puback_pacing.py` (flood cycles CONNECTED, batch shape, suppression, PINGREQ under flood), `test_client_puback_guard.py` (backstop still faults at the cap), `test_client_audit_fixes.py` (flood-survives + receipt order).

## Bake validation history

| Date | Steps active | Outcome |
|---|---|---|
| 2026-05-23 | Pre-convergence baseline | 5-min PLAIN bake, 290 publishes / 290 PUBACKs / 0 gaps -- happy path was always green; the defects only show on negative tests. |
| 2026-05-23 | Steps 1 + 2 (recv-zero + handle reorder) | 5-min PLAIN bake, 289 publishes / 289 PUBACKs / 0 gaps / heap steady -- confirmed no regression on the happy path. |
| 2026-05-23 | Steps 1–6 (recv-zero, reorder, send-timeout, POLLERR/POLLHUP, one-per-tick, polish) | 5-min PLAIN bake, 290 publishes / 290 PUBACKs / 0 inbound gaps / 0 outbound gaps / in_flight_final 0 / pending_final 0 / tx_queue_final 0 / duration_ms 300010 -- all six steps land without regression. |
| 2026-05-23 | Steps 1–6, A1 negative bake (broker hard-kill + restart) | **FAILED.** Board transitioned to FAILED on `pkill -9 mosquitto` (step 1's recv-zero fix worked correctly), then stayed FAILED for 240 s and never reconnected after broker restart. Mosquitto log: zero "New connection from <board>" events post-restart. Root cause was a separate defect in `MQTTClient.check()` that gated the FAILED state out of `Runner.tick`'s check-gate, making `_attempt_self_heal` unreachable. Steps 1-6 detected the broker death correctly but the recovery path the runner uses to call self-heal was locked out by an unrelated condition. Captured below as Step 7. |
| 2026-05-23 | Steps 1–7 (adds check() reachability fix), A1 + A2 negative bake | **PASS.** A1 (`pkill -9 mosquitto` at T0+60s, restart at T0+90s): TRANSITION connected→failed within one tick of broker death, ~470 SELF_HEAL attempts (each returning `socket factory failed: [Errno 104] ECONNRESET` while broker was down — RST propagated from the wifi-radio TCP stack), TRANSITION failed→connecting→connected within ~10 s of broker restart, publishes resumed. A2 (`pkill -TERM mosquitto` at T0+180s, restart at T0+210s): same shape, also recovered. Final: `sent 232 received 60 inbound_gaps 0 puback_total 231 in_flight_final 0`. Two follow-ups surfaced (not blocking the fix): inbound `received` count stayed at 60 from pre-A1 onward — the board does not re-subscribe after self-heal completes (this is A8 in the negative-testing-suite); and recovery latency is ~10 s of full-tick-rate retries against the wifi radio, making Decision 0081's connector motivation concrete (correctness restored, but the connect path still slams the runner during the outage). |
| 2026-07-04 | mqtt 0.23.0 (self-heal sandboxing + attempt deadline + PUBACK guard), A1 hard-kill bake, Pico W MP | **PASS — retry pacing proven.**  5 backoff-paced SELF_HEAL attempts across the 30 s outage (1-2-4-8-16 s schedule; the 2026-05-23 baseline burned ~470 full-tick-rate attempts in the same window), one-tick detection of the broker death, reconnect on the first post-restart attempt.  Final: `sent 273 puback_total 273 inbound_gaps 0 in_flight_final 0 tx_queue_final 0`, heap steady, zero handler faults.  The evening's first run false-negatived on a HARNESS defect, not a library one: the diag harness monkey-patches the private `_attempt_self_heal` with a zero-arg logging wrapper, which TypeErrors now that the method takes `now_ms` (surfaced instantly by the new `SERVICE_FAULT` wiring).  Fixed at the harness with the exact current signature — no `*args` drift-shim, per the no-backwards-compat posture; the wrapper itself is a deletion candidate next harness pass, since `on_handler_error` + `last_error` + state polling now cover its diagnostic role.  Observation for the rate-convergence pass: during the outage each attempt faults via the runner's `io_error` (POLLERR/POLLHUP on the connector's in-flight socket, eventmask 0x1c) before the connector's own POLLERR branch runs — redundant but correct, and faster detection. |
| 2026-07-04 | Same build, A2 graceful-TERM bake | **PASS — pre-connect queue drain proven.**  Same 5-attempt pacing; the graceful broker close takes the identical recv-zero detection path; at reconnect the CONNACK drained the 8-deep pre-connect queue (`in_flight 8 tx_queue 8` at the connected transition) and every drained publish was acked.  Final: `sent 274 puback_total 273 in_flight_final 1` — the last 1 Hz publish fired at the 300 s cutoff with its PUBACK still in flight, benign. |
| 2026-05-23 | Steps 1–8 (adds SUBSCRIBE replay on CONNACK), A1 + A2 negative bake | **PASS — inbound survives reconnect.** Same A1 + A2 schedule.  Inbound `received` count grew across both outages: pre-A1 49 → post-A1 109 → post-A2 229 → BAKE_END 289 (was frozen at 60 for the entire post-A1 window in the prior bake).  `inbound_gaps 0 puback_total 231 in_flight_final 0 tx_queue_final 0`.  Subscription replay restored the inbound stream both times.  The remaining concern is recovery latency (~10 s of full-tick-rate ECONNRESET retries while broker is down) — Decision 0081 territory, still open. |

The remaining negative-bake scenarios (NAT-style silent drop, broker dropped PUBACK, long broker outage, session resumption, etc.) from [`mqtt-negative-testing-suite.md`](mqtt-negative-testing-suite.md) are the next validation surface.

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
3. **Send timeout (`_waiting_to_send_timeout`)** — **LANDED** as commit `ffeee534` (2026-05-23).  Deadline-driven (no timer thread): `_send_deadline_ticks` arms on tx-queue-non-empty, re-arms on successful send, clears on queue-empty.  Surfaced via `next_deadline`, checked in `_check_deadlines`, FAILED transition with meaningful `last_error`.  New `send_timeout_seconds` constructor param (defaults to `ack_timeout_seconds`).  Two regression tests cover stuck-socket + steady-drip paths.
4. **POLLERR / POLLHUP surfacing** — **LANDED** as commit `fa7f32df` (2026-05-23).  Cross-library: `chumicro_runner.Runner.wait` now inspects the ipoll iterator instead of discarding it, and dispatches error events to a new optional `service.io_error(now_ms, eventmask)` hook on the matching registered service.  `chumicro_mqtt.MQTTClient.io_error` transitions to FAILED with the raw eventmask in `last_error`.  Five runner-side + two mqtt-side regression tests.
5. **Recv-first ordering, suppress-send-while-busy, one-chunk-per-tick** — **PARTIALLY LANDED** as commit `599a9615` (2026-05-23).  One recv per tick + one send per tick are in (closes MEDIUM-divergence C).  Multi-packet dispatch from the already-buffered decoder stays as-is because chumicro's runner doesn't fire on a tight loop the way the reference's monolithic `loop()` does.  Suppress-send-while-busy is naturally satisfied by the new partial-send-resume-and-return pattern; explicit `_packet_count_that_must_send` discipline isn't needed.
6. **Self-heal cost sandboxing, idempotent `disconnect`, will-after-construct** — **LANDED** (idempotent disconnect + public `set_will` as commit `5bd6dca6`, 2026-05-23; self-heal sandboxing completed 2026-07-04, mqtt 0.23.0).  Shipped shape: `transport_factory` produces a Decision-0098 `SocketConnector`, and first-connect and self-heal converge on ONE connect path — both enter `AWAITING_TRANSPORT` and advance the connector by at most one `tick()` per `handle()` call, with `io_socket` / `io_interest` forwarded to the connector so `Runner.wait` parks on handshake progress (sockets 0.17.1's handshake-direction-accurate interest flows through).  Retry pacing: the exponential self-heal backoff (1 s base doubling to a 60 s cap, int tick math, shipped mqtt 0.18.0) gates attempts; `next_deadline` surfaces the backoff deadline in FAILED (now also `now_ms` when no backoff is armed yet, so the runner wakes for the immediate first retry instead of parking on another service's socket).  Connect-attempt deadline: connectors report `next_deadline() is None` by design (consumer owns the deadline), so the client arms a per-attempt window inheriting `ack_timeout_seconds` — no new knob — checked in `handle()` *before* the connector tick (deadlines-before-I/O), surfaced through `next_deadline`, and on expiry the connector is `cancel()`ed and the client faults to FAILED with the connector phase in `last_error`.  `disconnect()` mid-attempt cancels the connector and stays idempotent.  Substrate limits stand: MP's TLS handshake and CP's whole connect are still one blocking tick each (documented in the sockets adapters) — the sandboxing win is structural on CPython, partial on the boards, and the retry-pacing + attempt-deadline wins apply everywhere.  Pending hardware bake (A1/A2 rerun should show paced retries instead of the ~470 full-tick-rate attempts recorded 2026-05-23).
7. **`check()` reachability for FAILED** — **LANDED** 2026-05-23 (commit `b7dcad1d`).  `MQTTClient.check()` previously returned `False` for both `DISCONNECTED` and `FAILED`; the runner gates `handle()` on `check()`, so `_attempt_self_heal` (which only fires from inside `handle()`'s FAILED branch) was unreachable from the runner.  The convergence-steps-1-6 fixes correctly transitioned to FAILED on broker death but the recovery path was then locked out.  Fix is one line: gate only on `DISCONNECTED` (the terminal user-initiated state); `FAILED` keeps the tick budget so self-heal can fire every tick until the broker is reachable again.  `handle()`'s FAILED branch already defensively gates on `_user_wants_connected`, so the no-self-heal case is bounded.  Regression test `test_check_returns_true_when_failed` in `libraries/mqtt/tests/test_client_oversize_errors.py` codifies the contract.  Bake-validated A1 + A2 in the same session — see the row above.
8. **SUBSCRIBE replay on CONNACK** — **LANDED** 2026-05-23.  `MQTTClient._subscriptions` (eagerly maintained dict of topic → requested-QoS, updated by `subscribe_raw` / `unsubscribe_raw` at call time) is replayed in `_replay_subscriptions` from `_handle_connack` after state lands in `CONNECTED`.  First-connect's CONNACK finds an empty set (no-op); a self-heal-driven CONNACK replays the surviving entries so a broker with `clean_session=True` (chumicro's default) doesn't leave the inbound stream silent after reconnect.  Replay does not fire the per-topic `on_subscribe` callback — `on_connect` fires next and is the right signal that "we re-subscribed."  Two regression tests in `libraries/mqtt/tests/test_client_acks_backpressure.py` (`test_subscription_replayed_on_self_heal_reconnect`, `test_unsubscribed_topic_not_replayed_on_reconnect`).  Bake-validated A1 + A2 in the same session — see the row above (`received` 60 → 289 across both outages).

## What is not in scope

- Decision 0080 (runner-reactor) rewrite.  Convergence happens within the existing ADR scope; if a fix surfaces something that conflicts with 0080, file an ADR addendum or supersession in `plans/decisions/`.
- mqtt_bake_diag harness improvements.  The harness's clock-domain mix bug (now using `chumicro_timing` exclusively) was a separate fix; further harness polish belongs elsewhere.
- Wifi-router cycle / "underlying socket fail" handling.  Open question whether that's a chumicro-mqtt or chumicro-wifi responsibility; routed to `plans/workstreams/mqtt-negative-testing-suite.md` for decision before code.

## Pointers

- Reference: a previous-generation MQTT client (1043-line monolithic `loop()`).
- Current `chumicro_mqtt.client`: `libraries/mqtt/src/chumicro_mqtt/client.py` (2008 lines, 2026-07-04).
- Current `chumicro_mqtt._wire`: `libraries/mqtt/src/chumicro_mqtt/_wire.py` (825 lines, 2026-07-04).
- Current `chumicro_runner.core`: `libraries/runner/src/chumicro_runner/core.py` (923 lines, 2026-07-04).
- Bake harness: `projects/mqtt_bake_diag*/` in the sibling workspace-template checkout.
- ADR for the runner contract: [`plans/decisions/0080-runner-reactor.md`](../decisions/0080-runner-reactor.md).
- ADR for the runner pattern (constraints on services): [`plans/decisions/0014-runner-pattern.md`](../decisions/0014-runner-pattern.md).
- Paired test workstream: [`plans/workstreams/mqtt-negative-testing-suite.md`](mqtt-negative-testing-suite.md).
