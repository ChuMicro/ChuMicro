# Decision 0064: `chumicro-mqtt` inbound size handling + topic-prefix sugar + ack-fault policy

Status: `accepted`
Date: `2026-05-12`
Summary: MQTT inbound has two tiers (steady ≤ `rx_buffer_size`, oversized = policy; middle tier removed by 0099); `root_topic`/`prefixed=` sugar (cut 2026-07-04); SUBACK 0x80 faults loudly.
Related: [Decision 0061](0061-whenoversized-cross-library-contract.md) (`WhenOversized` cross-library contract), [Decision 0010](0010-library-testability.md) (constructor injection), [Decision 0014](0014-runner-pattern.md) (tick-based runner).

## Context

A `chumicro-mqtt` audit comparing the current decoder against a reference implementation found one real bug, one dead public-API parameter, and a behavioral regression versus the reference:

1. **`max_message_bytes` constructor kwarg is dead.**  The value flows from `MQTTClient.__init__` into `PacketDecoder.__init__`, gets stored on `self._max_message_bytes` at `_wire.py:487`, and is never read anywhere else in the decoder.  The README, the user guide, and the docstring all describe it as the load-bearing cap on inbound payload size; the code ignores it.
2. **The "degraded" path allocates a payload-sized buffer.**  When an inbound PUBLISH exceeds `rx_buffer_size` (default 256 B), `_enter_oversized_path` allocates `bytearray(payload_to_drain)` — a one-shot buffer sized to the full remaining payload — drains the entire payload into it, then discards the buffer and emits an `_OversizedMessage` event.  A hostile or misconfigured 1 MB PUBLISH on a 256 KB-RAM board allocates 1 MB on the heap to throw it away.
3. **The decoder has no "valid but bigger than steady state" tier.**  Every PUBLISH whose total length exceeds `rx_buffer_size` becomes an `_OversizedMessage` event with no payload delivery, even when it's a normal 4 KB JSON sensor reading.  The reference implementation distinguishes three tiers and delivers mid-sized messages intact through a one-shot temporary buffer.

The audit also surfaced four missing-or-regressed pieces relative to the reference: no removal API for pattern handlers, silent acceptance of SUBACK failure codes, no topic-prefix sugar (`root_topic` + per-device prefixing), and no topic-binder convenience class.  And one latent deadlock: a PUBLISH whose topic alone exceeds `rx_buffer_size` causes `_enter_oversized_path` to wait forever for "more bytes to parse the prelude" while the buffer is full.

The fixes touch enough public API that a single ADR is the right place to nail the design.

## Decision

### 1. Three-tier inbound size handling

The decoder dispatches inbound PUBLISH into three tiers by `total_length` (fixed header + remaining length + payload):

| Tier | Condition | Behavior |
|------|-----------|----------|
| **Steady** | `total_length ≤ rx_buffer_size` (default 256 B) | Parse inline from the steady-state buffer. No allocation. Deliver via `on_message(topic, payload)`. |
| **Intact** | `rx_buffer_size < total_length ≤ max_message_bytes` (default 8 KB) | Allocate `bytearray(message_length)` one-shot, drain payload through the steady-state buffer into it, deliver via `on_message(topic, payload)`. Buffer drops out of scope after delivery; heap returns to the steady-state baseline. |
| **Oversized** | `total_length > max_message_bytes` | Apply the `WhenOversized` policy — see §2. |

The intact middle tier this decision added was later measured load-free (its two test pins were the only exercisers) and removed by [Decision 0099](0099-mqtt-surface-corrections.md): the steady→oversized boundary is now `rx_buffer_size` itself, `max_message_bytes` is gone, and a consumer expecting mid-sized payloads intact sizes `rx_buffer_size` accordingly.

### 2. Oversized-tier policy honors Decision 0061 verbatim

`WhenOversized` keeps its three-policy shape per the cross-library contract.  In the oversized tier:

| Policy | Behavior |
|--------|----------|
| `DROP_SILENT` | Drain the payload through the steady-state buffer in rolling fashion (no allocation beyond the existing rx buffer). No callback. Stay connected. |
| `DROP_WITH_EVENT` (default) | Drain through the rolling steady-state buffer. Fire `on_oversized(reported_length, topic)`. Stay connected. PUBACK on QoS 1. No truncated payload delivery. |
| `DISCONNECT` | Raise `MQTTProtocolError`. Skip the drain — the socket is being torn down anyway. |

The "drop the payload entirely; do not truncate" semantic matches `chumicro-requests` and `chumicro-websockets` per Decision 0061 §4.  Diagnostic information (`reported_length` + `topic`) is enough for application-side reaction; the actual payload bytes go in the bit bucket without a corresponding heap allocation.

No new buffer allocation happens in the oversized tier at all.  The rolling-drain pattern reuses the steady-state `rx_buffer`: each pass fills it from the socket, advances a "bytes still to drain" counter, then discards the filled buffer for the next pass.  Heap cost is constant regardless of the inbound message size.

### 3. Oversize-topic case folds into the oversized tier

A PUBLISH whose topic alone exceeds `rx_buffer_size` minus the small fixed-header overhead is treated as oversized under the same `WhenOversized` policy.  `topic=None` in the `on_oversized(reported_length, topic)` callback signals "the topic itself didn't fit in the steady-state buffer."  Under `DISCONNECT` the raised `MQTTProtocolError` names `rx_buffer_size` so the user can either shrink their topic strings or raise the cap.

This fixes a latent deadlock where the decoder kept returning `None` waiting for a prelude that would never fit.

### 4. Topic-prefix sugar: `root_topic` + per-call `prefixed=` opt-out

> **Cut 2026-07-04** by the mqtt bloat review ([reviews/2026-07-04-mqtt-bloat-review.md](../reviews/2026-07-04-mqtt-bloat-review.md), commit `924b3ab6`): shipped, then removed as set-by-no-runnable-consumer.  `root_topic` / `prefixed=` / `will_prefixed` do not exist on `MQTTClient`; apps build topics by f-string.  This section stays as the design record.

`MQTTClient` gains a `root_topic: str | None = None` constructor kwarg.  When set, every `publish` / `subscribe` / `unsubscribe` call automatically prefixes the topic:

| `root_topic` | Outbound topic | Example |
|--------------|----------------|---------|
| `None` | `<topic>` | `publish("temperature", v)` → `temperature` |
| Set | `<root_topic>/<client_id>/<topic>` | `MQTTClient(client_id="mainLightSwitch", root_topic="livingRoom")` + `publish("switchState", v)` → `livingRoom/mainLightSwitch/switchState` |

Each `publish` / `subscribe` / `unsubscribe` accepts `prefixed: bool = True` (default).  Pass `prefixed=False` to send a verbatim topic — system topics (`$SYS/...`), bridge topics, or anything outside the per-device hierarchy.

The will message uses the same shape: `will_topic` + `will_prefixed: bool = True` constructor kwargs.  The resolved bytes are computed once in `__init__`.

The inbound topic delivered to `on_message` is **not** prefix-aware: topics from the wire are delivered exactly as received.  (The `add_pattern_handler` router this paragraph once covered was removed by [Decision 0099](0099-mqtt-surface-corrections.md); per-topic routing is `on_message` + the public `topic_matches()`.)

### 5. No topic-binder wrapper — publish directly on the client

An earlier revision of this design added an `MQTTPublisher` topic-binder (a `client.publisher(topic, ...)` factory returning an object that held `(client, topic, qos, retain)` and delegated back to `client.publish`).  It was dropped: over a plain `MQTTClient.publish` call it saved only one bound argument per publish while adding a class, a factory method, and a second publish surface to document and test.  Neither `MQTTPublisher` nor `MQTTClient.publisher()` exists in the code.

The single publish entry point is `MQTTClient.publish(topic, payload, *, qos=0, retain=False, on_publish=None, prefixed=True)`.  One `publish` auto-detects `str` (UTF-8-encoded) vs `bytes` — there is no separate `publish_bytes` — resolves *topic* through the `root_topic` / `client_id` prefix scheme (§4) unless `prefixed=False`, and fires the optional `on_publish(topic, payload_bytes)` callback on successful delivery.  A caller that repeat-publishes to one topic passes the same topic string on each call.

### 6. Per-ack-type unexpected-packet policy

Unexpected acks (no matching pending entry) are handled per packet type:

| Packet | Policy | Reason |
|--------|--------|--------|
| **PUBACK** | Tolerate (ignore) | A duplicate PUBACK arrives legitimately when a retransmitted QoS-1 publish gets acked twice, so the client ignores an unmatched one (`test_unmatched_puback_is_tolerated`). |
| **SUBACK** | Fault | Same; SUBACK carries a packet ID we must have issued. |
| **UNSUBACK** | Fault | Same. |
| **PINGRESP** | Silently ignore | No packet ID; naturally racy in keepalive timeout / self-heal corners. |

The PINGRESP exception accommodates the case where a PINGREQ timeout fires (clearing the pending tracker, transitioning toward FAILED / self-heal) but the broker's PINGRESP arrives a tick later — re-faulting through a healthy connection would be a false positive.

Additionally, SUBACK with any `granted_qos` byte equal to `0x80` (subscription rejected by broker, per MQTT 3.1.1 §3.9.3) raises `MQTTProtocolError`.  Silently passing the rejection to the user callback was easy to miss; faulting transitions to FAILED + self-heal where the application can react.

### 7. Pattern-handler removal

`remove_pattern_handler(handler, pattern=None)` removes either every registration of `handler` (when `pattern=None`) or only the registration matching the `(pattern, handler)` pair.  Mirrors `add_pattern_handler`.  Long-running applications need to tear down subscriptions without holding closures forever.

## Rejected

**Tier-3 truncated-payload delivery.**  Earlier in the design pass we considered tier 3 allocating `bytearray(max_message_bytes)`, filling it with the first chunk of payload, and firing `on_oversized(reported_length, topic, truncated_payload)`.  Rejected: conflicts with Decision 0061 §4's "drop the oversized payload" semantic shared across `chumicro-mqtt` / `chumicro-requests` / `chumicro-websockets`.  Diagnostic value of the first 8 KB is real but recoverable other ways (broker logs, wireshark) when needed; the cost of re-diverging the cross-library contract for it isn't worth paying.  If a future use case needs it, add it as a separate policy value (`TRUNCATE_WITH_EVENT`) or an opt-in kwarg without disturbing the existing three.

**Separate `publish_raw` / `subscribe_raw` / `unsubscribe_raw` methods.**  Initially chosen on the argument that a separate method names the prefix-vs-raw intent at the API surface, where a per-call boolean kwarg scatters the decision across every callsite.  Reversed after the audit-embedded skill grew a wrapper-doubling check ([SKILL.md §1](../../.github/skills/audit-embedded/SKILL.md) + [field-reality.md](../../.github/skills/audit-embedded/field-reality.md#publish--publish_raw-wrapper-doubling)): six methods where three would suffice cost ~100 lines of duplicated body + duplicated docstring + extra qstr-interned method names + extra class-dict entries on every instance, all for one helper call's worth of difference.  The boolean-kwarg shape matches `set_will`'s existing `prefixed=` opt-out and stays consistent across the four prefix-aware entry points (publish, subscribe, unsubscribe, will).

**`include_client_id` boolean kwarg.**  The reference implementation we audited has this; we considered copying it on the initial design pass.  Rejected then in favor of `*_raw` methods, and still rejected against today's `prefixed=` kwarg only because the *name* is wrong: `include_client_id` describes one piece of the prefix scheme (the `<client_id>` segment) but not the `<root_topic>` segment.  `prefixed=True/False` names the binary decision actually being made.

**Required `client_id` floor for `rx_buffer_size`.**  Considered enforcing `rx_buffer_size ≥ 64` at construction.  Rejected: anyone setting it lower will get a clear `MQTTProtocolError` on the first inbound packet whose fixed-header + varlen exceeds their cap.  A constructor-time floor over-engineers a self-correcting failure mode.

**Shared `chumicro-policies` micro-library or shared `Policy` base class.**  Same reasoning as Decision 0061 §Rejected: not worth a fourth library three libraries depend on.

## Consequences

- **Public API:**
  - `MQTTClient(root_topic=...)` — new optional constructor kwarg.
  - `MQTTClient(will_topic=..., will_prefixed=True)` — semantic change: prefixed by default when `root_topic` is set; pass `will_prefixed=False` to bypass.
  - `MQTTClient.publish / subscribe / unsubscribe` — gain `prefixed: bool = True` kwarg (default preserves prefix-aware behavior; `prefixed=False` is the verbatim opt-out).
  - `MQTTClient.remove_pattern_handler(handler, pattern=None)` — new method.
  - `WhenOversized` enum + `on_oversized(reported_length, topic)` signature unchanged (Decision 0061 contract).
  - `max_message_bytes` now functional with default 8192.  Previously defaulted to 256 KB and was ignored.
- **Behavior changes that may surprise existing users:**
  - Inbound PUBLISHes between `rx_buffer_size + 1` and `max_message_bytes` now arrive on `on_message` with their full payload, where they previously fired `on_oversized` with `reported_length` and no payload.
  - Inbound PUBLISHes above 8 KB now hit the oversized tier where they previously hit the (incorrectly named) oversized path at 256 B.  Apps that were quietly relying on the bug to receive 5 KB messages via `on_oversized` need to either raise `max_message_bytes` or wire `on_message`.  Apps with `on_message` already wired (the common case) become more functional, not less.
  - SUBACK with rejection code `0x80` now faults to FAILED instead of silently passing the rejection to the user callback.  Apps that were silently ignoring failed subscriptions will start surfacing them.
- **No backwards-compatibility shims.**  Pre-1.0 (current VERSION 0.9.0 → 0.10.0, minor).  Edit forward.
- **Decision 0061 contract preserved.**  `on_oversized(reported_length, topic)` signature unchanged; `WhenOversized.DROP_WITH_EVENT` semantic ("drop the payload, stay connected") matches the shared cross-library contract.
- **Tests:** `test_decoder.py` gains intact-tier coverage + per-policy oversized-tier coverage + oversize-topic coverage.  `test_client.py` gains coverage for prefix resolution, the `prefixed=False` opt-out, `remove_pattern_handler`, SUBACK 0x80 fault, unexpected-PUBACK/SUBACK/UNSUBACK fault, unexpected-PINGRESP toleration.
- **Docs:** README's "What's included" table + `docs/guide.md`'s Oversized-message policy section + Memory-notes section + Tuning section are rewritten for the three-tier model and the new defaults.  The 256 KB number in those docs is wrong everywhere; this pass corrects it.
- **Version bump:** `chumicro-mqtt` `0.9.0` → `0.10.0`.  Minor bump — three public-method additions, one constructor-kwarg addition (`root_topic`), one will-kwarg rename (`will_topic` semantic change + new `will_topic_raw`), one behavior change in the steady-state-vs-oversized boundary.  All within the pre-1.0 SemVer policy.
