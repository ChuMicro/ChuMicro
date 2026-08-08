# chumicro_mqtt — bloat review: capability-paid-for vs fat

Date: 2026-07-04
Scope: `libraries/mqtt/src/chumicro_mqtt/{client.py,_wire.py}` — the 2833-line
pair — measured against a located 1043-line previous-generation reference.
READ-ONLY. Version 0.20.1, nothing published (Decision 0092 — breaks are free
pre-publication; *work* is not).

HEAD pinned: `68a997dca9292901cdb2073b20918a1150250bd3` (branch `main`). Line
references are to the tree at that commit; a sibling agent may be editing the
self-heal path concurrently, so treat any drift in `handle` / `_attempt_self_heal`
as newer-than-this-read.

Reference located: the pre-chumicro `basefs/mqtt_client.py` in a local scratch project
— **exactly 1043 lines**, the monolithic `loop()` (476-557) the convergence
workstream cites. (Two near-siblings exist in that scratch tree at 1165 and
1061 lines — the 1043 file is the one
the workstream's line numbers resolve against.)

---

## Headline — the honest denominator

The "2833 vs 1043" framing (2.7×) is **65 % prose**. On code the gap is 1.85×,
and nearly every extra code line is a capability the reference does not have.

| metric | client.py | _wire.py | **chumicro pair** | reference | delta |
|---|---:|---:|---:|---:|---:|
| total lines (`wc -l`) | 2008 | 825 | **2833** | 1043 | **+1790** |
| blank | 198 | 139 | 337 | 136 | +201 |
| comment (`#`) | 261 | 92 | 353 | 65 | +288 |
| docstring | 607 | 172 | 779 | 106 | +673 |
| **code lines** | **943** | **423** | **1366** | **737** | **+629** |

- **Of the +1790 total-line gap, +1161 (65 %) is docstrings + comments +
  blanks.** Only **+629 is code.**
- Real deploys strip docstrings/comments (Decision 0090). Stripped through the
  workbench minifier (`chumicro_deploy.source_minify.strip_source`):

  | file | raw bytes | stripped bytes | prose removed |
  |---|---:|---:|---:|
  | client.py | 92 468 | 38 513 | **58.3 %** |
  | _wire.py | 31 384 | 16 307 | 48.0 % |
  | **pair** | 123 852 | **54 820** | 55.7 % |
  | reference | 41 136 | 32 548 | **20.9 %** |

  On device the pair is **54.8 KB vs 32.5 KB = +68 %**, not +172 %. The
  reference is barely commented (strips 21 %), so the line count flatters it;
  measure code, not prose. (mpy floor, from `2026-07-03-di-cost-measurement.md`:
  mqtt CORE 20 070 B `.mpy`, DI-factory 588 B `.mpy`, import heap ~42 KB.)

**Verdict up front:** chumicro_mqtt is **not code-bloated**. The +629 code
lines are ~one-for-one capability the reference lacks (self-heal, runner-contract
split, multi-pending, QoS-1 table, pre-connect queue, session honesty,
`from_config`, `next_message`). The genuine fat is small: ~30 code lines of
**speculative config surface** (a topic-prefix scheme with zero consumers, one
dead `when_disconnected` value) plus a decoder helper orphaned by Decision 0099.
The dominant cost is **docstring density** — free on flash, but it is what makes
the file *read* 2.7× the reference and it charges test-lane heap.

---

## Method / comparanda

The reference is a MicroPython client with a monolithic `loop()` called directly
by the app. Structural map (agent-verified against the 1043-line file):

- **Has:** partial-send resume + send-timeout, a two-tier partial/degraded
  decoder, a QoS-1 single-message retransmit, a **pattern-handler router**
  (`register_handler`/`unregister_handler`/`on_message_handlers`) and an
  `MQTTPublisher` topic-binder — the last two are exactly what Decision 0099 /
  0064 **deleted** from chumicro.
- **Lacks (all present in chumicro):** non-blocking DNS/TCP/TLS connect
  (reference blocks inside `get_socket`), self-heal / auto-reconnect,
  backoff, permanent-vs-transient CONNACK latching, subscription replay,
  a multi-entry pending-response table (reference has **one** `_waiting_state`
  slot and refuses to send while any ack is outstanding — strictly serialized),
  a QoS-1 in-flight **table** with collision-checked id allocation (reference
  holds one in-flight message), backpressure-as-error (reference silently
  drop-oldests a 1000-deep deque), a durable pre-connect queue (reference loses
  `_tx_queue` on any disconnect), session-present honesty (reference hard-codes
  CleanSession=1 and ignores the bit), and `from_config` / DI.

So the correct baseline is: chumicro **added ~450 code lines of capability the
reference has none of, and deleted ~130 lines the reference carries** (pattern
router + MQTTPublisher), for a net +629. The comparison is capability-for-lines,
not fat-for-lines.

Prior art this review builds on and updates:
`2026-07-03-mqtt-api-fitness.md` reviewed the **pre-0099** tree (1917+907,
three-tier decoder, pattern router live). Since then, its top findings have
**landed**: the intact decoder tier and pattern router are gone (0099), the
pre-connect queue + `when_disconnected=` policy exist, and session-present is
now wired (§ Structural notes below). This pass judges the slimmer post-0099
tree.

---

## Block-by-block classification

Legend: **C** = capability (earns its size), **S** = structural overhead
(docstrings / DI / seams), **F** = fat candidate. Code-line counts are
docstring/comment/blank-excluded.

### client.py

| lines | block | code | class | what it buys / why it costs |
|---|---|---:|:--:|---|
| 1-14 | module docstring | 0 | S | on-ramp prose; strips to 0 |
| 16-48 | imports + `_IO_READ/_WRITE` literals | ~30 | C | runner-bit literals held (not imported) so no runner dep-edge |
| 55-80 | `ProtocolState` (5 states) | ~7 | C | 5 states are the floor for non-blocking connect + self-heal (ref has 3) |
| 83-110 | `InboundPublish`, `_InboundWait` | ~12 | C | `next_message` value object + park sentinel (Decision 0089) |
| 113-138 | `_AWAIT_*` tags, self-heal + permanent-CONNACK constants | ~10 | C | self-heal backoff schedule + latch codes |
| 141-179 | `InFlightPublish`, `PendingResponse` | ~15 | C | QoS-1 table entry + multi-pending entry (ref: one slot, no classes) |
| 187-203 | `WhenOversized` policy | ~5 | C* | shared cross-library contract (Decision 0061); see Fat-note |
| 205-238 | `_no_callback`, `_new_tx_queue`, `_force_non_blocking` | ~20 | C | cross-runtime deque (MP `flags=1` vs CPython), non-blocking-socket guard |
| 260-318 | `from_config` | 38 | S | DI factory (Decision 0093); 588 B mpy; **46 real consumers** — keep |
| 320-587 | `__init__` | 107 | S/F | 105 docstring lines (S); the config **surface** carries the prefix-scheme + never-tuned knobs (F) |
| 592-736 | `connect` / `_enqueue_connect_packet` / `disconnect` / `_reset_transient_state` | ~70 | C | async-connect entry + idempotent multi-state teardown |
| 738-781 | `set_will` | 22 | C | runtime will setter (1 consumer; closes an api-fitness gap) |
| 787-795 | `_prefixed_topic` | 4 | **F** | topic-prefix scheme — **zero consumers** |
| 797-958 | `publish` / `_publish_disconnected` / `_drain_pre_connect_queue` / `_do_publish` | ~83 | C/F | QoS-0 marker + QoS-1 in-flight open + **pre-connect queue** (C); `drop_oldest` branch + `prefixed=` (F) |
| 960-1046 | `subscribe` / `unsubscribe` | ~56 | C | eager `_subscriptions` set feeds replay; `prefixed=` slice is F |
| 1048-1111 | `next_message` / `_inbound_stream_ended` | ~19 | C | receive-stream surface (Decision 0089); 8 consumers |
| 1117-1263 | runner contract: `check` / `io_socket` / `io_interest` / `io_error` / `next_deadline` | ~70 | C | Decision 0080 cooperative-tick surface — reference has **none** (it is one `loop()`) |
| 1265-1343 | `handle` (the tick engine) | 32 | C | deadlines-first ordering, self-heal + connector-advance fall-through |
| 1345-1433 | `_arm_self_heal_backoff` / `_attempt_self_heal` / `_advance_connector` | ~48 | C | self-heal with backoff + non-blocking connector state machine |
| 1439-1455 | `_allocate_packet_id` | 11 | C | 1-65535 wrap + collision skip + `OverflowError` (ref: bare counter, no check) |
| 1461-1614 | TX path: `_drain_tx_queue` / `_update_send_deadline` / `_drain_callback_markers` / `_send_raw` / `_enqueue_user_tx` / `_enqueue_internal_tx` | ~68 | C | one-send-per-tick, partial-send resume, send-timeout arm, **backpressure-as-error** + protocol headroom (ref: silent drop-oldest) |
| 1620-1720 | RX path: `_read_inbound` / `_handle_inbound_publish` / `_handle_oversized` | ~60 | C | one-recv-per-tick + budget, receipt-order PUBACK flush, oversized policy dispatch |
| 1722-1837 | `_handle_ack` / `_handle_connack` | ~71 | C | multi-ack routing, dup-PUBACK tolerance, permanent-latch, session-present gate, replay+drain trigger |
| 1839-1909 | `_replay_subscriptions` / `_evict_rejected_subscription` / `_discard_pending` | ~38 | C | reconnect resilience + multi-pending match (ref: no replay at all) |
| 1915-2008 | `_check_deadlines` / `_check_keepalive` / `_deadline` | ~60 | C | QoS-1 retry, pending expiry, send-timeout, half-interval keepalive |

`*` `WhenOversized` all three members are exercised by sibling libraries
(websockets/requests define the same enum) — see Structural / cross-library note.

### _wire.py

| lines | block | code | class | note |
|---|---|---:|:--:|---|
| 1-9 | module docstring | 0 | S | prose |
| 25-59 | 5 exception classes | ~15 | C | typed errors incl. `MQTTBackpressureError`, `MQTTConnectError(return_code=)` — callers branch on them |
| 68-82 | packet-type constants | ~13 | C | `const()`-wrapped, pre-encoded PINGREQ/DISCONNECT |
| 90-169 | codecs: `encode_varlen` / `decode_varlen` / `encode_string` / `_append_*` | ~55 | C | alloc-light `pack_into` encoders |
| 171-205 | `_topic_levels_match` + `topic_matches` | ~18 | **F** | split helper **orphaned by Decision 0099** — see Fat-2 |
| 216-383 | encoders: connect/publish/subscribe/unsubscribe/puback | ~90 | C | wire builders |
| 397-447 | `ParsedPublish` / `ParsedAck` / `_OversizedMessage` | ~30 | C | parse results incl. `session_present` field |
| 456-825 | `PacketDecoder` (two-tier) | ~175 | C | steady inline parse + oversized rolling-discard (anti-OOM on a 264 KB board); read-cursor + amortized compaction |

---

## Capability accounting — what the +629 code lines buy, what deleting breaks

Grouped, with reference behaviour and the break-if-deleted:

| capability | ~code lines | reference | delete ⇒ breaks |
|---|---:|---|---|
| **Self-heal**: backoff, permanent-latch, `io_error`→FAILED, connector rebuild | ~90 | ABSENT (every fault raises to caller) | multi-week unattended uptime; the workstream's whole point |
| **Runner-contract split** (`check`/`io_socket`/`io_interest`/`io_error`/`next_deadline`) | ~70 | ABSENT (monolithic `loop()`) | cooperative-tick model (Decision 0080); board would block per-service |
| **Multi-pending + QoS-1 in-flight table** (`PendingResponse` list, `_in_flight` dict, collision-checked ids, dup-PUBACK tolerance) | ~118 | one wait slot, one in-flight msg, no collision check | concurrent SUB+PUB+PING; would serialize and stall the runner |
| **Two-tier decoder** (`PacketDecoder`) | ~175 (wire) | partial/degraded tiers exist | anti-OOM guarantee vs hostile oversize |
| **Pre-connect queue + `when_disconnected`** | ~24 | queues in `_tx_queue`, **lost on disconnect** | publish-before-connected (every consumer's common path) |
| **Subscription replay + eviction + session-present gate** | ~26 | ABSENT | inbound stream survives a reconnect |
| **`next_message` receive-stream** | ~19 | ABSENT | Decision 0089 linear-consumer surface (8 consumers) |
| **`from_config` DI** | 38 (588 B mpy) | ABSENT | one-line config construction (46 consumers) |
| **Backpressure-as-error + headroom** | ~25 | silent drop-oldest | a runaway publisher is told, not silently dropped |

Every row is capability the reference does not deliver. None is a deletion
candidate; the api-fitness pass already classified the analogous surfaces RIGHT.

---

## Structural overhead (measured, mostly free-on-device)

- **Docstrings dominate the raw delta.** 779 docstring + 353 comment = 1132
  prose lines (40 % of 2833). Decision 0090 strips them at deploy → **0 flash
  bytes** — this is why the on-device gap is +68 % not +172 %. What they *do*
  cost: (a) **test-lane heap** — the unix test lanes import UNSTRIPPED, so the
  ~42 KB mqtt import heap carries docstring objects the board never sees; (b)
  reader time. The single heaviest block is `__init__`'s ~105-line Args
  docstring (320-452). This is on-ramp documentation, not bloat; do **not** cut
  for size. A targeted density trim (below) is optional and belongs to a
  `/regen-comments` pass, not a structural cut.
- **DI / `from_config` / `sockets_factory.py` (43 lines) / `__chumicro_skip_factories__` hatch.** Measured at 588 B mpy (di-cost review); 46 consumers. This is the Decision-0093 contract, not ceremony. Keep.
- **`testing.py` (109 lines, `__chumicro_test_support__=True`).** `canned_*_bytes` + `new_client`/`drive`. Test seam, never flashed (2086 B "test-only strip"). Keep.
- **Cross-library note (integration, not mqtt-local):** `WhenOversized` is
  defined **three times** — `mqtt/client.py:187`, `websockets/_session.py:67`,
  `requests/client.py:96` — same three string constants each. Within mqtt only
  `DROP_WITH_EVENT` (the default) has a real consumer (`bench.py`); `DROP_SILENT`
  / `DISCONNECT` are tests-only. But the siblings exercise all three, so the
  enum is a shared contract, not mqtt fat. If anything, the three copies should
  **converge** into one shared module — an `/audit-integration` item, out of
  scope here.
- **Session-resume is now correct (not half-built).** `_wire._parse_connack`
  reads `session_present` (688), `_handle_connack` gates replay on it (1832),
  and `_attempt_self_heal` preserves the in-flight table when
  `clean_session=False` (1392). The api-fitness "half-wired knob" finding is
  **resolved.** Caveat: **zero consumers set `clean_session=False`**, so the
  machinery (~10 code lines) is correct-but-unexercised — a bundle candidate if
  the fleet commits to clean-only.
- **Tests-only public surface (cheap keeps, not fat):** `unsubscribe` has **no**
  external caller (tests only); `on_disconnect` / `on_unsubscribe` callbacks and
  the `InboundPublish` / `MQTTConnectError` / `MQTTProtocolError` /
  `UnsupportedQoSError` exports are tests-only. Each is a mirror-of-a-used-thing
  or a typed-error class costing a line or two — keep for surface symmetry.
- **API-churn signal (before-publication concern, not mqtt-source fat):** the
  factory kwarg is now `transport_factory` and it has **no sister-repo
  consumer** — every `ChuMicro-Workspace-Template` project still constructs
  `MQTTClient(socket_factory=…)` or `MQTTClient(connector_factory=…)` (e.g.
  `projects/mqtt_tls_probe/app.py:126`, `mqtt_bake_diag_plain/app.py:191`);
  **neither kwarg exists** in the audited `__init__`, so those calls would
  `TypeError`. The most-visible downstream consumers are pinned to an older
  bundled API across two renames (`socket_factory`→`connector_factory`→
  `transport_factory`). Legal under 0092, but it says the constructor surface is
  not settled — freeze the factory-kwarg name before publication. (Fix belongs
  to the template repo; noted here as read-only evidence.)

---

## Fat candidates (savings / stripped-bytes / breaks / migration)

Byte estimates use the measured code density (~41 B/stripped-code-line for
client.py); docstring lines are ~0 device bytes but full raw bytes on the test
lane.

### Fat-1 — the `root_topic` topic-prefix scheme — **cut now**

`root_topic` (kwarg, `client.py:326`), `will_prefixed` (334), `prefixed=` on
`publish`/`subscribe`/`unsubscribe`/`set_will`, and `_prefixed_topic` (787-795).

- **Evidence it is dead:** `root_topic` is set by **no runnable consumer**
  (only guide.md:299 names it, in prose) and is **not even read by
  `from_config`** (the one kwarg missing from the config path). With
  `root_topic=None` (always), `_prefixed_topic` returns the topic unchanged, so
  `prefixed=True` and `prefixed=False` are **identical no-ops**. Every one of
  the **7** real `prefixed=` usages passes `prefixed=False` (all in
  `demos/mqtt_pub_sub/{app,driver}.py`) — defensively opting out of a feature
  nobody turns on.
- **Savings:** ~15 code lines + ~40 docstring lines; ~600 B device,
  ~1.5 KB test-lane. Removes a kwarg from 4 method signatures and 2 constructor
  kwargs.
- **Breaks:** 7 demo callsites + 1 `set_will` call carry a now-unknown kwarg →
  delete the kwarg (mechanical). Zero behaviour change (they are no-ops today).
  Also touches the guide (`docs/guide.md:299,313,317` document `root_topic` /
  `prefixed=` / `will_prefixed`) — one doc edit, part of the same cut.
- **Migration under 0092:** trivial, free break. A fleet that later wants
  per-device namespacing prepends the prefix at the callsite (one f-string) or
  re-adds the scheme deliberately, config-driven this time.

### Fat-2 — `_topic_levels_match` split, orphaned by 0099 — **cut now**

`_wire.py:171-205`. The hand-indexed `_topic_levels_match` exists (per its own
docstring) "for a caller matching N patterns against one inbound topic
[that] caches the pattern splits at registration time." **That caller was the
pattern-handler router, deleted by Decision 0099.** The only surviving caller is
`topic_matches` (205), which splits fresh every call — so the split-out helper
and its caching rationale are now dead weight, and the docstring describes a
consumer that no longer exists.

- **Savings:** ~10 code + ~15 docstring lines by inlining into `topic_matches`;
  ~400 B device.
- **Breaks:** none (`_topic_levels_match` is private, one internal caller).
  `topic_matches` stays public and unchanged in behaviour.
- **Note:** `topic_matches` itself is **tests-only** (consumers: `test_packets.py`,
  `test_mosquitto_integration_pytest.py`; no demo/example/sister/guide callsite).
  Keep it public anyway — api-fitness blessed it as the routing primitive that
  *replaces* the deleted router — but collapse the internal two-function split.

### Fat-3 — `when_disconnected="drop_oldest"` — **bundle with next wave**

`_publish_disconnected` (861-885) supports three policy values; **`drop_oldest`
has zero consumers** (`queue` and `raise` are the only ones used, 3 callsites).

- **Savings:** ~5 code + ~8 docstring lines; validation narrows to
  `{"queue","raise"}`.
- **Breaks:** none. **Migration:** trivial. Low urgency — the branch is cheap;
  bundle it with the next mqtt touch rather than spending a commit now.

### Fat-4 — never-tuned buffer/timeout knobs — **bundle / keep**

`pre_connect_queue_size`, `recv_budget_per_tick`, `send_timeout_seconds`,
`max_inbound_queue_size`, `max_tx_queue_size` — **none is set by any real
consumer** (defaults ride). Each is a cheap stored attribute; the cost is
docstring surface, which strips on device. These are legitimate escape hatches
(a bursty publisher wants `max_tx_queue_size`), so **keep the mechanisms**;
optionally demote the two least-plausible (`recv_budget_per_tick`,
`max_inbound_queue_size`) to module constants if trimming constructor surface in
a later wave. Not worth a break now.

---

## Ranked punch list

### Cut now — free, zero-consumer, removes real surface
1. **Delete the `root_topic` prefix scheme** (Fat-1). ~15 code + ~40 docstring
   lines, ~600 B device. All 7 real `prefixed=` usages are `False` no-ops;
   `root_topic` set by nobody and absent from `from_config`. Break = drop the
   kwarg from 7 demo callsites + 1 `set_will`. Free under 0092.
2. **Collapse `_topic_levels_match` into `topic_matches`** (Fat-2). ~10 code +
   ~15 docstring lines. The caching rationale's caller was deleted by 0099; the
   docstring now lies. Breaks nothing.

### Bundle with the next mqtt wave — cheap, low urgency
3. **Drop `when_disconnected="drop_oldest"`** (Fat-3) — zero consumers; narrow
   validation to `{"queue","raise"}`. ~5 lines.
4. **Demote never-tuned knobs to constants** (Fat-4, the two least-plausible) —
   reclaims constructor surface + docstring only; keep the mechanisms.
5. **Revisit the `clean_session=False` session-resume machinery** — correct but
   unexercised (~10 code lines); drop with `clean_session` only if the fleet
   commits to clean-only.

### Keep — with rationale
- **Self-heal + backoff + permanent-latch** (~90) — reference has none; the
  reason this library exists.
- **Runner-contract split** `check`/`io_*`/`next_deadline` (~70) — Decision 0080;
  reference is a single blocking `loop()`.
- **Multi-pending + QoS-1 in-flight table** (~118) — reference serializes on one
  slot and would stall the runner.
- **Two-tier `PacketDecoder`** (~175, _wire) — anti-OOM on 264 KB RAM.
- **`from_config`** (38 code / 588 B mpy) — 46 consumers.
- **`next_message` / `InboundPublish`** (~19) — Decision 0089, 8 consumers.
- **`WhenOversized`** — shared cross-library contract; converge the 3 copies via
  `/audit-integration`, don't cut here.
- **Docstrings** (779 lines) — Decision 0090 strips them; the on-device gap is
  +68 %, not +172 %. Charge them to test-lane heap and reader time, not flash.
  Only a `/regen-comments` density pass (not a structural cut) is warranted, and
  Fat-1 already deletes the most-repeated paragraph (the prefix scheme).

---

## Bottom line

Net cuttable **now** without losing a capability any consumer uses:
**~25 code lines + ~55 docstring lines (~1 KB device, ~2.5 KB test-lane)** —
the prefix scheme and the orphaned decoder helper. Everything else in the
+629-code-line delta is capability the 1043-line reference simply does not have.
The file is not fat; it is *thoroughly documented* capability. The right lever
for the "why is it 2.7× the reference" question is the **denominator** (measure
code, not prose), not the knife.
