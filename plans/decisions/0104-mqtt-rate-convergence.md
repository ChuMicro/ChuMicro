# Decision 0104: mqtt inbound/outbound rate convergence (coalesced PUBACK batch + recv suppression)

Status: `accepted`
Date: `2026-07-04`
Summary: Per-tick inbound PUBACKs coalesce into one front-of-queue batch flushed outside the send budget; the recv is suppressed while it is unsent, so acks track dispatch and TCP backpressure bounds memory.
Related: 0080 (runner reactor), 0099 (surface corrections), the cooperative-tick convergence workstream (divergence C, deep-review MQTT-2)

## Context

The one-recv + one-send-per-tick shape (convergence step 5) left a rate hole: a single
1 KB recv can surface ~146 tiny QoS-1 PUBLISHes from the buffered decoder, each owing a
PUBACK appendleft, while the drain retires one packet per tick.  Inbound dispatch rate
was unbounded relative to outbound drain rate; a fast broker grew the backlog to the tx
hard cap (user cap + 64) and tripped the interim guard shipped 2026-07-04 — fault to
FAILED rather than silently evicting a protocol packet.  Correct but ugly: a healthy
flood became a reconnect cycle, and the broker's redelivery re-created the same flood.
Any real fix had to preserve wire ordering (MQTT-4.6.0-2 receipt-order acks), QoS-1
at-least-once, the ≤5 ms tick, the allocation-light hot path, and bounded memory on
264 KB boards — and keep PINGREQ injectable during sustained inbound.

## Decision

1. **Coalesce.**  `_read_inbound` collects the tick's PUBACKs (receipt order) and
   enqueues them as ONE front-of-queue `bytes` entry — `b"".join` only when >1, so the
   single-ack common case allocates nothing extra.  Queue growth from inbound QoS-1 is
   ≤1 entry per tick regardless of inbound rate; batch size is bounded by
   `recv_budget_per_tick` (bytes recv'd bounds packets dispatched bounds acks owed).
2. **Budget-free flush.**  `_drain_tx_queue` sends a head-of-queue PUBACK batch (first
   byte 0x40 — unique among outbound packets) without consuming its one-packet-per-tick
   budget: at most two send syscalls per tick.  Acks leave in the tick they were
   incurred, so the ack rate tracks the dispatch rate and PINGREQ / user publishes keep
   the send slot under sustained inbound (no keepalive starvation, no retry exhaustion).
3. **Suppress the recv while acks are owed.**  While the batch (or any partial send) is
   unsent, the tick skips its recv and `io_interest` drops the read bit.  Unread bytes
   stay in the kernel buffer; the TCP receive window closes; the broker throttles at its
   end.  Bounds OUR memory, not just our dispatch — and structurally pins cross-tick
   PUBACK receipt order (a second batch cannot queue in front of an unsent first).
   Deadlines still run before the read (step-2 ordering), so suppression never defers
   fault detection; the send timeout bounds how long a wedged socket holds it.
4. **The hard-cap guard stays** as the last-resort correctness net (fault to FAILED,
   never drop a protocol packet), now reachable only when retransmits/replays have
   already consumed the whole 64-slot protocol headroom.

## Consequences

- A QoS-1 flood cycles smoothly: flood tests drive 120 publishes through a
  4-slot user queue with zero faults and all 120 acks on the wire in receipt order.
- The tick's syscall ceiling rises from recv+send to recv+2×send — an explicit,
  bounded amendment to divergence C's "one send per tick" (the batch send is small:
  4 bytes per ack, ≤ ~600 B at the default recv budget).
- `recv_budget_per_tick` becomes the single inbound pacing lever (tick latency,
  per-tick dispatch count, and batch size) and earns its constructor-kwarg seat.
- Steady-state QoS-0 cost is unchanged (empty-list check per tick); QoS-1 inbound
  adds one join per multi-ack tick on top of the existing per-ack encode.
- Suppression trades inbound-ack read latency for bounded memory while the socket is
  congested: broker PUBACKs to our own publishes sit unread for the (send-timeout-
  bounded) suppression window.  Ack deadlines are 5 s; drain progress lifts
  suppression within a tick, so the trade is theoretical outside a genuinely dead link.

## Rejected

- **Fixed-K per-tick dispatch bound.**  Converges only at K=1 (any K>1 still outruns a
  1/tick drain), throttling QoS-0 subscribers to one message per tick for no reason;
  needs new decoder-peek + wake-deadline plumbing to avoid stalling buffered packets
  until the keepalive tick (the exact stall step 5 documented when it kept multi-packet
  dispatch); and still starves user traffic behind front-inserted acks.
- **Dispatch budget coupled to drain headroom.**  Lets the backlog march to the cap and
  park there; front-inserted PUBACKs then permanently occupy the single send slot
  (insertion rate == drain rate), starving user publishes into retry-exhaustion faults
  and PINGREQ into PINGRESP timeout during >35 s floods.
- **Suppress-only (no coalescing).**  The burst inside a single recv (~146 acks vs a
  64-slot headroom) reaches the guard before suppression can engage.
- **Dedicated PUBACK lane outside the tx queue.**  Behaviorally equivalent to the
  coalesced batch but new machinery: a second partial-send state, a second overflow
  guard, and the loss of the existing guard site and its regression tests.  The batch
  reuses queue, partial-send resume, send-timeout, and guard verbatim.
