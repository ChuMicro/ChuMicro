# Decision 0119: on_disconnect fires when an established session ends

Status: `accepted`
Date: `2026-08-09`
Summary: `MQTTClient.on_disconnect` fires on link loss (CONNECTED to FAILED) as well as on explicit `disconnect()`. Connect attempts that never established, including the self-heal retry cycle, stay silent.
Related: Decision [0108](0108-connect-is-intent-not-a-transition.md) (connect is intent), Decision [0114](0114-mqtt-client-id-per-device.md) (client identity)

## Context

`on_disconnect` fired only from an explicit `disconnect()` call.  A consumer wiring session cleanup to it never heard about link loss: the client dropped to FAILED, self-heal dialed in the background, and the callback stayed silent until the user themselves hung up.  The docs stated this honestly, and consumers were told to poll `state` / `last_error`, which is exactly the polling the callback exists to remove.

The design question was which FAILED transitions count.  The client enters FAILED from ten sites: synchronous connect failures, transport-connect timeouts, connector faults, CONNACK rejections, mid-session I/O faults, ack timeouts, and the runner's POLLERR/POLLHUP dispatch.  Firing on every entry would spam the callback once per backoff attempt through a broker outage, turning "the session ended" into "a dial attempt failed", which `last_error` already reports.

## Decision

`on_disconnect` reports the end of an established session, mirroring `on_connect`, which reports its start.  It fires when:

- `disconnect()` tears down any non-DISCONNECTED state (unchanged), or
- the client leaves CONNECTED for FAILED: an I/O fault mid-session, an ack timeout, a send timeout, or the runner's poll-error dispatch.

It stays silent when a connect attempt fails from DISCONNECTED, AWAITING_TRANSPORT or CONNECTING, and through every self-heal retry.  An outage therefore fires it exactly once per established session lost, and a recovered session that drops again fires it again.

All ten FAILED entries route through one chokepoint, `_enter_failed()`, which reads the prior state, settles `state = FAILED`, and fires the callback last.  Ordering is the reentrancy contract: every site sets `last_error` before the transition, and the state is settled before the callback runs, so a reentrant `connect()`, `hold()` or `disconnect()` from inside the callback sees FAILED, not the dying state.  A reentrant `disconnect()` transitions to DISCONNECTED and fires the callback once more, which is coherent: two events happened.

## Consequences

- The mqtt demos' `on_wifi_state` handlers and the guide's hold/connect composition keep working unchanged; the new fire is additive.
- A raising `on_disconnect` propagates out of `handle()` like any other callback raise; the client is already settled in FAILED when it does.
- Consumers that only ever called `disconnect()` see no change.  Consumers that polled `state` for drops can move that logic into the callback.
