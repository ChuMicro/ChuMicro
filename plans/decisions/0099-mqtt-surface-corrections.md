# Decision 0099: mqtt surface corrections

Status: `accepted`
Date: `2026-07-03`
Summary: mqtt gains a bounded pre-connect publish queue, drops the intact decoder tier and the pattern-handler router, and makes session resumption honest.
Related: 0089 (inbound surfaces — amended in place on acceptance), 0064 (its §5 is already stale and gets the same edit), campaign report `plans/reviews/2026-07-03-mqtt-api-fitness.md`

## Context

The 2026-07-03 fitness review judged the reactive client architecture right and most
surfaces earning their size, with four exceptions.  `publish()` raises unless CONNECTED
and every consumer in both repos writes the same guard around it — a universal
workaround is an API verdict.  The three-tier decoder's intact-drain middle tier spends
~350 lines on a profile the docs themselves call rare, while only the oversized tier
delivers the anti-OOM win.  The pattern-handler router is a third inbound surface beside
Decision 0089's two, used once, trivially.  And the CONNACK session-present flag is
parsed then ignored, so `clean_session=False` silently does not do what it says.

## Decision

1. **Pre-connect queue**: `publish()` before CONNECTED enqueues into a small bounded
   queue (`pre_connect_queue_size=8`) drained on CONNACK before `on_connect`, governed by
   `when_disconnected=` (queue / raise — a third `drop_oldest` policy shipped with this
   wave but was cut as zero-consumer by the 2026-07-04 bloat review), defaulting to
   queue; a full queue under "queue" raises the same backpressure error as the tx queue.
   The universal caller guard is deleted everywhere.  `subscribe()` is a declaration valid
   in any state: it records the topic in the eagerly-maintained desired-set (already replayed
   on CONNACK), sends the SUBSCRIBE immediately when CONNECTED, and otherwise leaves the first
   CONNACK's existing replay path to put it on the wire.  A pre-connect declaration is exactly
   a replay-set entry, and the session-present gate already skips replay when the broker
   resumed the session — so the resumed-session case needs no special handling and the
   pre-connect-interaction worry dissolves.  `on_subscribe` becomes a one-shot stored with the
   entry, firing on the first SUBACK that grants the topic (direct send or replay) then
   clearing, so self-heal replays stay callback-silent.  Consumers may still subscribe in
   `on_connect`; it is now one valid placement among equals, not a requirement.
2. **Decoder**: drop the intact-drain tier; keep steady + oversized-discard.  With two
   tiers the steady→oversized boundary is `rx_buffer_size` itself, so `max_message_bytes`
   goes with the tier (a dead knob otherwise).  Measured payoff: both unix lanes drop
   256K→240K.
3. **Router**: delete the pattern-handler surface; `on_message` + `next_message()` (0089)
   plus the public `topic_matches()` cover its one use.
4. **Session honesty**: session-present is honored (replay skipped when the broker
   resumed) rather than refusing `clean_session=False` — the client already preserved
   the QoS-1 in-flight table across self-heal reconnects, so gating the replay was the
   last missing piece, not a half-wire.

## Consequences

Roughly 500 lines leave the client; consumers simplify (the flagship app's try/except
publish scaffolding deletes).  0089 and 0064 get their in-place edits on acceptance.
Ships as campaign Wave 2, after the timing/sockets waves, bake-gated on the mqtt demo.
