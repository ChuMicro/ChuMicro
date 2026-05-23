# Workstream: chumicro_mqtt + chumicro_runner cooperative-tick convergence

Status: **proposed.**  Surfaced 2026-05-23 during the Pi Pico W CP TLS bake investigation.  Owner intends to pick this up in a later session.

## Problem

`chumicro_mqtt` and `chumicro_runner` diverge from the cooperative-tick discipline that a proven reference implementation has run in production with multi-week uptimes.  Reference: `~/circuitpython/pythonProject3/basefilesystem/lib/basefs/mqtt_client.py` (the user's `loop()` method around line 476-558 plus `_read_socket` at 651-672).

The divergences span multiple files and patterns; the workstream is **holistic** — fix the patterns together, don't pick at them one at a time.  The bake on 2026-05-23 surfaced concrete instances; **a deeper read of the reference implementation against the chumicro stack is expected to find more.**

## What the reference impl does that chumicro should match

These are the patterns the reference has battle-tested.  Each maps to a concrete chumicro defect noted in the same row.

| Reference behavior | chumicro current behavior | File:line |
|---|---|---|
| Deadline / ack-timeout checks **first**, before any socket I/O | `handle()` runs `_drain_tx → _read_inbound → _check_deadlines → _check_keepalive → _drain_tx` — deadline check is downstream of read.  A stuck recv blocks the deadline detection that would have caught the hung connection. | `libraries/mqtt/src/chumicro_mqtt/client.py:872-876` |
| `recv_into() == 0` ⇒ peer closed ⇒ disconnect + raise | `_read_inbound` silently `break`s the loop on `got == 0`, leaves `state` as `CONNECTED`.  Self-heal never fires for a clean TCP FIN. | `libraries/mqtt/src/chumicro_mqtt/client.py:1060-1061` |
| `POLLERR` / `POLLHUP` from `ipoll` → disconnect + raise | Runner's `wait()` discards the event iterator entirely: `for _ in self._poller.ipoll(timeout_ms): pass`.  Error / hangup events are ignored, and the per-event readiness info isn't surfaced at all. | `libraries/runner/src/chumicro_runner/core.py:386-387` |
| Poll **readiness** drives I/O — only call `recv` when `POLLIN` set, only call `send` when `POLLOUT` set | Services blindly call `recv_into` / `send` on every `handle()`, then let the socket's non-blocking semantics surface EAGAIN.  Wastes ticks polling-with-no-data and assumes recv / send return EAGAIN cleanly under every CP edge case. | architecture, not one site |
| Receive first (per the user's confirmed design call), then send.  The recv side may produce PUBACKs that clear `_in_flight` slots so the next send isn't blocked by an artificially-full in-flight table. | The current order (`drain_tx → read → drain_tx`) sends before AND after reading; not the intentional discipline. | client.py:872-876 |
| One chunk per tick in both directions — recv reads whatever's there in **one** `recv_into` call and returns; send transmits **one** queued packet (or one partial-send continuation) and returns | `_read_inbound` loops `while consumed < budget` calling `recv_into` repeatedly (up to 1024 B / tick by default).  `_drain_tx_queue` loops `while self._tx_queue:` sending until empty or block.  Both can hold the runner on a single service for many ms while other services (LED, buttons, LCD) stall. | `libraries/mqtt/src/chumicro_mqtt/client.py:1042-1063` (read), `:977-994` (drain) |

## Other strays / improvements — research pass needed

The bake investigation surfaced the above by accident.  This workstream's load-bearing task is the **deeper holistic pass**: read the reference `mqtt_client.py` end-to-end against `chumicro_mqtt`'s `client.py` and `_wire.py`, and `chumicro_runner`'s `core.py`, and list every other divergence — design, error handling, naming, state shape, retry policy, callback signatures, ordering invariants, whatever.  Some candidates to consider but the list is not exhaustive:

- **Connection setup ordering** — the reference's `_queue_connect_packet` + how it sequences POLLOUT-mask changes vs `WAIT_CONNACK`.  Chumicro's `connect()` is more straightforward but may miss cases.
- **Partial-send recovery** — reference's `_partial_state` handling.  Chumicro has `self._partial_send = (packet, offset)` but the path is `pragma: no cover`.  Reference exercises it heavily.
- **Outbound-event-mask juggling** — reference modifies the poll mask between `READ_ONLY_MASK` and `READ_WRITE_MASK` based on whether `_tx_queue` is non-empty (loop lines 516-518 + 548-550).  Avoids spurious POLLOUT wakeups on every tick.  Chumicro has no equivalent.
- **Retransmit on PUBACK timeout** — reference's `WAIT_PUBACK` path with `_publish_retransmit` flag and DUP-bit set.  Chumicro has `_check_deadlines` retry logic but the retry-limit / failure semantics may differ.
- **`waiting_to_send_timeout`** — reference disconnects if a packet sits queued too long without a writable socket.  Chumicro has no such timer.
- **Callback contract** — reference's callback signatures (`on_publish`, `on_message`, etc.) and when they fire.  Chumicro's `on_publish(topic, payload)` was a surprise (the diag bake initially assumed `(packet_id)`); the broader contract may have other surprises.
- **State-machine shape** — reference's `_connection_state` + `_waiting_state` two-axis model vs chumicro's single `ProtocolState`.  Chumicro may be missing intermediate states for the timing windows the reference covers.
- **Error normalization** — how each layer translates `OSError` / `MQTTError` / runtime exceptions into state transitions.

When this workstream is picked up, **start with that deeper read**, not the punch-list above.  The punch-list items will likely change shape (and gain siblings) after the read.

## How to verify the convergence

The bake harness (`projects/mqtt_bake_diag/` in workspace-template) is the load test.  After fixes, the bake should:

- Publish 1 Hz from `BAKE_START`, no startup lag.
- Hold `1-blocks`, `free`, `max_free_sz`, `floor` steady across all 30s checkpoints.
- Survive a deliberate broker disconnect (kill mosquitto mid-bake) → board detects, transitions to `FAILED`, self-heal kicks in when broker restarts.
- Survive a NAT-style silent drop (e.g. `pfctl block` on the broker IP from the board) → board hits ack-timeout within `ack_timeout_seconds + ε`, transitions to `FAILED`, self-heal on next tick.

The reference impl satisfies all four against multi-week uptime tests.

## What is not in scope

- Decision 0080 (runner-reactor) rewrite.  The convergence happens within the existing ADR scope; if the read surfaces something that conflicts with 0080, file an ADR addendum or supersession in `plans/decisions/`.
- mqtt_bake_diag harness improvements.  The harness's clock-domain mix bug (now using `chumicro_timing` exclusively) was a separate fix; further harness polish belongs elsewhere.

## Pointers

- Reference: `/Users/chuxor/circuitpython/pythonProject3/basefilesystem/lib/basefs/mqtt_client.py`
- Current `chumicro_mqtt.client`: `libraries/mqtt/src/chumicro_mqtt/client.py`
- Current `chumicro_runner.core`: `libraries/runner/src/chumicro_runner/core.py`
- Bake harness: `~/circuitpython/ChuMicro-Workspace-Template/projects/mqtt_bake_diag*/`
- ADR for the runner contract: [`plans/decisions/0080-runner-reactor.md`](../decisions/0080-runner-reactor.md)
- ADR for the runner pattern (constraints on services): [`plans/decisions/0014-runner-pattern.md`](../decisions/0014-runner-pattern.md)
