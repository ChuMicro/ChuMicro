# Decision 0099: mqtt surface corrections

Status: `proposed`
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
   queue drained on CONNACK, governed by a `when_disconnected=` policy (queue / raise /
   drop-oldest), defaulting to queue.  The universal caller guard is deleted everywhere.
2. **Decoder**: drop the intact-drain tier; keep steady + oversized-discard.
3. **Router**: delete the pattern-handler surface; `on_message` + `next_message()` (0089)
   plus the public `topic_matches()` cover its one use.
4. **Session honesty**: honor session-present (skip subscription replay when the broker
   resumed) or refuse `clean_session=False` loudly — no silent middle.

## Consequences

Roughly 500 lines leave the client; consumers simplify (the flagship app's try/except
publish scaffolding deletes).  0089 and 0064 get their in-place edits on acceptance.
Ships as campaign Wave 2, after the timing/sockets waves, bake-gated on the mqtt demo.
