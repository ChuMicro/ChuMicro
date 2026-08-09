# Decision 0108: connect() is an intent, not a state transition

Status: `accepted`
Date: `2026-07-05`
Summary: `connect()` is an intent (dial from DISCONNECTED, immediate self-heal from FAILED, no-op mid-connect) with a symmetric caller `hold()`; the app steers reconnection, the timer is the fallback.
Related: 0081 (non-blocking connect — first-connect and self-heal already share one connector path), 0098 (transport_factory / connect-path collapse), 0099 (pre-connect publish queue), 0104 (self-heal rate convergence + backoff), 0092 (no-backwards-compat posture informs the minimal surface); resolves the "Where wifi-router cycle belongs" open question in `plans/workstreams/mqtt-negative-testing-suite.md`

## Context

`connect()` was a state-transition guard: it raised `MQTTError("connect() requires DISCONNECTED state, was …")` in any state but DISCONNECTED, and reconnection from FAILED was owned exclusively by the self-heal timer (exponential backoff 1→2→4→…→60 s).  The canonical wifi wiring — `on_wifi_state CONNECTED → mqtt.connect()` — therefore raised on every recovery after the first (the client is FAILED / AWAITING_TRANSPORT mid-self-heal, never DISCONNECTED), and even when swallowed it left the client to wait out residual backoff.  The 2026-07-05 board-initiated wifi-drop bench measured the cost: the recovery callback fired at 86.6 s but self-heal did not reconnect until 98.7 s — 12 s wasted waiting out backoff the caller already knew was pointless.  The user's call: "if I call connect it should connect if I'm not connected… having to wait for some timer when I can say 'connect now please' seems off."  The symmetric gap: when the app KNOWS the link is down, a timer dialing into a dead radio is wasted cycles (and on ESP-IDF the socket dials plausibly contend with the radio's own re-association).

## Decision

**One reconnect machinery, two triggers, plus a caller hold.**  Reconnection intent is steered by the app when it has information; the timer is the fallback when it doesn't.

### `connect()` is an intent

- **DISCONNECTED** → begin the connect flow exactly as before (build the connector → AWAITING_TRANSPORT, or queue CONNECT against a pre-built socket → CONNECTING).
- **FAILED** → "self-heal now".  Clear the permanent-failure latch and the caller hold, reset the backoff schedule to its base (`_self_heal_attempts = 0`, `_self_heal_retry_at_ticks = None`), and let the next `handle()` tick fire the **same** self-heal path a timer would — `next_deadline` returns *now* so the runner ticks it immediately.  `connect()` does **not** dial inline; it re-arms, and the shared `_attempt_self_heal` (socket close, transient reset, clean-session in-flight clear, connector build) runs on the tick.  Queue / in-flight / clean-session fate is byte-identical to a timer-fired self-heal because it *is* the timer's path, just un-paced.  A subsequent failure re-paces from the 1 s base.
- **AWAITING_TRANSPORT / CONNECTING / CONNECTED** → idempotent no-op.  The intent "be connected" is already being satisfied; no second connector, no state disturbance.

In every state `connect()` clears any caller hold and latches the connected intent, so it is the sole hold release and lifts a preemptive hold placed while still CONNECTED.

### `hold()` is the symmetric primitive

`hold()` is a pure intent latch (`_reconnect_held = True`): it changes no state and cancels no in-flight dial.  Once the client is FAILED the hold suppresses self-heal — no connector is built, the state stays FAILED with `last_error` preserved, `next_deadline` returns `None` (park cleanly, no busy-wake), and `check()` gates the client out of dispatch.  Publishes issued while held follow the existing `when_disconnected` policy (buffer by default, flush on the eventual reconnect's CONNACK).  Called while CONNECTED / CONNECTING / AWAITING_TRANSPORT the latch is dormant (those states never self-heal) and takes effect the moment the link fails to FAILED.

The three self-heal gates (`handle()`, `next_deadline()`, `check()`) share one predicate, `_self_heal_active()` — factory present, user asked to connect, no permanent rejection, not held — so the dial and the runner scheduling that feeds it stay in lockstep.  A hold is deliberately *not* treated as inbound-stream-ended: it is releasable, so `next_message()` suspends rather than terminating.

### The app composes; neither library self-steers

`MQTTClient` is transport-agnostic and never imports or watches a radio (it runs on CPython lanes with no wifi).  The app that owns both the wifi service and the client composes them:

```python
def on_wifi_state(old, new):
    if new == WifiState.CONNECTED:
        mqtt.connect()    # link back: reconnect now (also clears the hold)
    else:
        mqtt.hold()       # link down or still dialing: stop dialing
```

(`WifiService` reports link loss as `RECONNECTING`, then `FAILED` once retries are exhausted; it never re-enters `DISCONNECTED` after construction.  Keying the hold on "any state but CONNECTED" covers both and stays dormant during initial bring-up, when `connect()` has not yet been called.)

`connect()` is the sole hold release — no separate `resume_reconnect()` (release-without-dial) primitive.  The canonical need is "wifi up → dial now"; a zero-consumer "release but keep waiting" verb is exactly the speculative surface the no-backwards-compat posture (0092) and the 0099 policy-cut precedent tell us to omit.

### The double-actor concern

The old raise doubled as a guard against building a second connector while one was in flight.  That guard is preserved without the raise: `connect()` from AWAITING_TRANSPORT / CONNECTING / CONNECTED is a no-op (no second connector), and `connect()` from FAILED re-arms the *shared* self-heal path rather than dialing inline, so exactly one connector is ever built — by `handle()`, on a tick, through 0081's single connect path.  Dispatch is cooperative and single-threaded, so `connect()` and `handle()` never interleave.  There is no documented race the raise prevented beyond "don't build two connectors," and that invariant now lives in the no-op rule.

## Consequences

- The natural wifi-recovery wiring is now correct and encouraged: `connect()` on recovery reconnects at once instead of raising and instead of waiting out backoff; `hold()` on drop stops the timer from storming a dead radio.  The guide's "connect-once rule" is replaced accordingly; the publish-fate documentation is unchanged.
- Resolves the "Where wifi-router cycle belongs" question routed to `plans/workstreams/mqtt-negative-testing-suite.md` (B2 / B6): **neither** library owns cross-service coordination.  chumicro-mqtt owns "I saw my socket fail, retry" (self-heal, the fallback); the app owns "the radio is down / up" and expresses it through `hold()` / `connect()`.  No wifi dependency edge is added to mqtt.
- `MQTTClient` gains one public method (`hold()`) and no new constructor knob.  Ships as mqtt 0.26.0 (behavior change; no release tags exist, so no compat shim — 0092).
- Tests: `test_client_wifi_outage_publish_fate.py`'s raise-pinning test is flipped to pin immediate reconnect + identical queue fate; `test_client_connect_lifecycle.py`'s CONNECTING-raise test is flipped to the idempotent no-op; new `test_client_connect_intent.py` covers the intent semantics (no-op states, immediate dial short-circuiting backoff, base-repace, timer-vs-connect queue equivalence) and `test_client_hold_reconnect.py` covers hold (timer suppression, park, buffer-while-held, release-and-flush, latch-while-connected).
- The 240 K unix-lane heap budgets are held (no ratchet): `hold()` and the reworked `connect()` grow the client's *unstripped* import chain enough to load-OOM the two near-ceiling MP suite files, so those were split per the suite-slimming convention — `test_decoder.py` → `test_decoder_error_paths.py` (wedge/varlen, protocol errors, oversized tier) and `test_client_connector_selfheal.py` → `test_client_selfheal_replay.py` (replay + explicit-disconnect gating) — collected count unchanged.  Production import is unaffected either way (deploy strips docstrings, Decision 0090).
