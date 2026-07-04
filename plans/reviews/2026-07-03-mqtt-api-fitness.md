# chumicro_mqtt — API-fitness review

Date: 2026-07-03
Scope: adversarial *is-this-the-right-API* review of `libraries/mqtt`
(`client.py` 1917 lines + `_wire.py` 907 lines; testing.py 109,
sockets_factory.py 46, `__init__.py` 37 — ~3016 src total). READ-ONLY.
VERSION 0.20.1, nothing published (Decision 0092 — breaks are free).

The question is not "is the code correct." It reads as correct and
carefully tested (20 test modules, 4165 test lines). The question is
"is this the right *shape* for a 264 KB cross-runtime board." Verdicts
per surface below, then the three biggest shape mistakes.

---

## Method / comparanda

Judged the shape against, from knowledge (flagged where unsure):

- **umqtt.simple** (MicroPython): ~150 lines. Blocking `connect()`,
  `publish()`, `check_msg()`/`wait_msg()`. QoS 0/1. No reconnect.
- **umqtt.robust**: umqtt.simple + a blocking auto-reconnect wrapper
  around every call. Still blocking.
- **adafruit_minimqtt** (CircuitPython): ~700 lines. Blocking
  `connect()`/`loop(timeout)`. QoS 0/1 (QoS 2 unsupported). Callback
  `on_message`, `add_topic_callback` (the direct analog of this lib's
  pattern handlers), Last-Will, retain, `is_connected`.
- **paho-mqtt** (CPython): ~5000 lines, threaded `loop_start()`,
  offline message queue, full QoS 0/1/2, `reconnect_delay_set`.
- **aiomqtt**: ~1500 lines, async-context-manager wrapper over paho.

Structural fact that dominates every verdict: **async is banned on
device code and the runner is a cooperative single-thread tick loop
(Decisions 0014/0080/0089/0091).** None of the five comparanda fit that
model — four are blocking, one is async. So a bespoke reactive
`check`/`handle`/`io_*`/`next_deadline` client is *necessarily* larger
than umqtt/MiniMQTT and cannot just adopt their shape. That is the
correct baseline against which "overbuilt" has to be argued — not
against a 150-line blocking client that solves a different problem.

---

## Per-surface verdicts

### 1. Connect lifecycle + connector-factory self-heal — **RIGHT**

`connect()` (client.py:552) either queues CONNECT against a pre-built
socket (→ CONNECTING) or invokes `connector_factory()` and enters
AWAITING_TRANSPORT, driving DNS/TCP/TLS one phase per tick inside
`handle()` (client.py:1247, `_advance_connector` 1333). Self-heal on
FAILED rebuilds a fresh connector with exponential backoff
(1 s→60 s, `_arm_self_heal_backoff` 1272) and latches permanent failure
on CONNACK codes 1/2/4/5 (`_PERMANENT_CONNACK_CODES` 134, 1735).
Subscriptions replay on every CONNACK (`_replay_subscriptions` 1748) so
the inbound stream survives a reconnect.

This is the strongest surface in the library and the clearest
justification for its size. It is strictly more capable than
umqtt.robust (which reconnects but *blocks* the whole board doing it —
the exact 10 s stall Decision 0081 measured and killed) and than
MiniMQTT (no self-heal at all). The non-blocking connect, the
backoff, the permanent-vs-transient CONNACK split, and the
subscription replay are each real capability a runner-shaped board
wants and none of the comparanda deliver together. The five-state
machine (client.py:49) is honestly the minimum for "non-blocking
connect + self-heal." Keep as-is.

Minor: `io_error`/`next_deadline`/`io_wants_read` runner-contract
surface (client.py:1048-1190) is idiomatic to this workspace and not
negotiable given the runner model.

### 2. Publish semantics — **WRONG-SHAPE (the headline finding)**

`publish()` (client.py:752) **raises `MQTTError` when the client is not
CONNECTED** (client.py:793-796); `subscribe()` (887) and
`unsubscribe()` (923) do the same. Because connect is asynchronous
(§1), there is a live window — AWAITING_TRANSPORT / CONNECTING, plus
every self-heal outage — during which the mainstream "connect then
publish" idiom throws.

Evidence that this default is wrong: **every consumer in the repo works
around it.**
- Demo `demos/mqtt_pub_sub/app.py:63` moves *all* setup into
  `on_connect` and guards the periodic publisher with
  `if mqtt.state != ProtocolState.CONNECTED: return` (:106).
- `examples/telemetry.py:118` drives a `_drive_until(CONNECTED)` loop
  before it may subscribe/publish.
- Sister-repo `example_sensor/app.py` gates its `HeartbeatPublisher`
  on `state != CONNECTED` in `check()` and wraps `publish()` in
  `try/except` (its `handle`).
- Guide getting-started (docs/guide.md:24-35) has to *teach* the
  workaround: "subscribe()/publish() require CONNECTED … wire them
  through on_connect."

paho and MiniMQTT do not export this: `connect()` is synchronous, so a
following `publish()` "just works," and paho additionally queues
offline. chumicro correctly chose async connect for the runner — but
then handed the *consequence* of that choice to every caller instead of
absorbing it. That is the API mistake: the state-guard ceremony is paid
at the common path, not the exceptional one.

Better shape (sketch): a bounded pre-connect buffer flushed on CONNACK,
with a per-call policy for the disconnected case rather than an
unconditional raise —

```python
def publish(self, topic, payload, *, qos=0, retain=False,
            when_disconnected="queue"):  # "queue" | "drop" | "raise"
    ...  # "queue": bounded, flushed after CONNACK / self-heal reconnect
```

`when_disconnected="queue"` as the default would delete the
on_connect-dance from all four consumers above.

### 3. Backpressure-as-error — **BORDERLINE / OVERBUILT-edge**

`MQTTBackpressureError` (_wire.py:48) is raised by `publish()` when the
tx queue is at `max_tx_queue_size` (default 20; `_enqueue_user_tx`
client.py:1490). For the target profile (publish every N seconds, queue
sits near zero — the guide says so, docs/guide.md:221) this never
fires; when it does, an *exception on a fire-and-forget QoS-0 telemetry
publish* is a heavy shape. The sister-repo sensor already has to
`try/except` publish for exactly this. For QoS 1 "tell me you couldn't
enqueue" is defensible; for QoS 0 best-effort, drop-oldest or a boolean
return matches the caller's actual intent better than a raise.
Not a top-3 mistake, but it compounds #2 — between them, every publish
site in the repo is wrapped in defensive plumbing.

### 4. subscribe + pattern handlers vs `next_message()` — **next_message RIGHT; pattern-handler subsystem OVERBUILT**

Three inbound surfaces coexist:
- `on_message` catch-all (client.py:524) — **right**, the baseline.
- `add_pattern_handler` / `remove_pattern_handler` (client.py:1011,
  1023) with a hand-indexed wildcard matcher (`_topic_levels_match`
  _wire.py:171) — **overbuilt / redundant.**
- `next_message()` generator (client.py:946), Decision 0089's
  receive-stream flavor, first call flips delivery from callbacks to a
  bounded drop-oldest queue — **right, and cheap** (~50 lines reusing a
  deque; mirrors websockets per 0089).

Decision 0089 deliberately blesses the `on_message`↔`next_message` pair
(fan-out vs linear consumer) and that pairing is genuinely good. The
odd one out is the **pattern-handler subsystem**: it is a second,
in-library topic router bolted onto `on_message`. Real usage is thin —
the demo registers exactly one handler for `demo/+/cmd`
(app.py:121) purely to emit a marker, and no example or sister-repo
project uses it at all. `on_message` plus the already-public
`topic_matches()` (_wire.py:199) covers every observed need. The
add/remove pair, the not-prefixed-matching caveat, and the "pick one
surface, not both" cognitive load (guide.md:101) are API surface
without demonstrated demand. MiniMQTT ships the same idea
(`add_topic_callback`), so it is not unprecedented — but on a 264 KB
board with a public `topic_matches`, it is the clearest candidate for
deletion. **Verdict: both 0089 surfaces belong; cut the pattern-handler
router.**

### 5. `from_config` — **RIGHT**

client.py:256. Reads flat `mqtt.*` keys, lazy-imports
`sockets_factory` behind the `__chumicro_skip_factories__` hatch,
raises a named `RuntimeError` when excluded (:294), validates the
mapping shape up front (:280). Matches the Decision 0093 factory
contract exactly (side-effect-free construction, endpoint baked into a
zero-arg closure, classmethod). Clean. No change.

### 6. `WhenOversized` policy object — **RIGHT** (but the decoder behind it is overbuilt — see §7)

The policy enum itself (client.py:183, `_handle_oversized` 1622) is a
three-string class honoring the Decision 0061 cross-library contract
(`reported_length` first callback arg, `DROP_WITH_EVENT` stays
connected, `max_message_bytes` naming). Cheap, shared-shaped, correct.
On a board where a hostile 1 MB PUBLISH is a real OOM vector, having a
*policy* for oversize is right. Keep the enum.

### 7. Three-tier decoder machinery — **OVERBUILT (defensible, but the middle tier is speculative)**

`PacketDecoder` (_wire.py:459) implements three inbound tiers: steady
(≤ rx_buffer_size 256 B, inline), **intact** (≤ max_message_bytes 8 KB,
one-shot `bytearray(payload_length)`, `_DRAIN_INTACT`), oversized
(rolling discard, `_DRAIN_OVERSIZED`). This is ~350 lines: two drain
modes, `fill_buffer`/`fill_capacity`/`advance` branching three ways,
`_enter_intact_drain` (_wire.py:826), `_enter_oversized_drain` (852),
`_maybe_finish_*` (867/882).

The safety win — never allocate a payload-sized buffer for a hostile
oversize — comes entirely from **tier 3 (rolling discard)**. The
**intact tier (tier 2) is the speculative middle**: the library's own
sizing table (guide.md:343-357) shows the entire realistic payload
profile (sensor readings, small/medium JSON, prefixed status) lands in
**steady**, and tells the user to `rx_buffer_size=512` if they exceed
it. Tier 2 exists to deliver a 4 KB JSON without permanently pinning a
4 KB steady buffer — a real transient-vs-persistent RAM tradeoff, so
this is defensible, not wrong. But it is a whole second drain state
machine (~150 lines) for a case the docs describe as uncommon, and the
only place it is meaningfully exercised is the synthetic `bench.py`.

Better shape: two tiers — steady parse, oversize → policy via rolling
discard — and let a user who needs 4 KB intact set `rx_buffer_size`
(the docs already coach exactly this). Removes `_DRAIN_INTACT` and its
buffer-seeding entirely. If intact-without-persistent-RAM is a genuine
requirement, keep it, but it should be named as the deliberate cost it
is, not presented as free.

### 8. QoS coverage — **RIGHT**

QoS 0 and 1; QoS 2 raises `UnsupportedQoSError` (client.py:797,
_wire.py:304, and on the will 724). This matches embedded reality
exactly: umqtt does 0/1, MiniMQTT explicitly drops QoS 2. QoS 2's
four-packet handshake + persistent store is not something a 264 KB
sensor wants. Rejecting it loudly (rather than silently downgrading) is
the correct call. No change.

### 9. Missing / half-built capabilities

- **Last-Will + retained — RIGHT.** Full will config
  (topic/message/qos/retain/prefixed) resolved once at CONNECT
  (client.py:451, `set_will` 693), retain on publish. On par with
  paho/MiniMQTT. The demo's presence-pair (online/offline will) shows
  it working end-to-end.
- **Reconnect semantics — RIGHT** (see §1).
- **Session resume — UNDERBUILT (misleading knob).** `clean_session`
  exists and the in-flight QoS-1 table is preserved across self-heal
  only when it is False (client.py:1314-1321). *But* CONNACK's
  session-present bit is parsed and then **discarded** (`_parse_connack`
  _wire.py:698-705 skips byte 0), and `_replay_subscriptions`
  (client.py:1748) re-subscribes on **every** reconnect regardless of
  clean_session. So with `clean_session=False` the client cannot tell
  whether the broker actually kept its state, and re-subscribes anyway —
  defeating the resume optimization the knob advertises. The parameter
  is present; the behavior behind it is half-wired. Either act on
  session-present (skip replay when the broker confirms the session
  survived; force a full re-subscribe when it did not) or drop
  `clean_session=False` support and document clean-only.
- **Offline queueing — MISSING** (see §2). No store-and-forward; the
  publish-before-connected window raises. Acceptable for a pure
  publish-when-connected sensor, but it is the missing capability that
  makes #2 sting.
- **Keepalive under deep-sleep — ACCEPTABLE via self-heal.** Keepalive
  is tick-driven off `ticks_ms` (`_check_keepalive` client.py:1885); a
  board that deep-sleeps past the interval will have its connection
  dropped by the broker and recovered by self-heal on wake. No special
  handling, and none is really needed given self-heal — but the guide
  never says so, and a user reasoning about `keep_alive_seconds`
  wouldn't know the interaction. One doc sentence, not code.

### 10. ~2800 lines — capability or bloat? — **MOSTLY CAPABILITY, two overbuilt pockets**

client.py 1917 + _wire.py 907 = 2824. That is ~4x MiniMQTT and ~18x
umqtt.simple — but those are blocking clients solving a smaller
problem. The delta over MiniMQTT buys: non-blocking tick-driven connect
+ connector state machine, self-heal with backoff + permanent-latch,
subscription replay, partial-send/send-timeout/backpressure bookkeeping
for a non-blocking socket, and heap-bounded RX. Those are real and
runner-mandated.

Two caveats keep this from being "bloat":
- **Docstrings are stripped at deploy (Decision 0090)** and the bare
  import measures ≤ 44 KB under the MP default (Decision 0094). A large
  fraction of the 2824 lines is prose that never reaches flash; the
  line count materially overstates on-device cost.
- Genuine capability justifies ~1500-1800 lines. The remaining
  ~400-600 sit in the two overbuilt pockets already named: the intact
  decoder tier (§7, ~150) and the pattern-handler router (§4). Cutting
  both is a real slim without losing a capability any consumer uses.

Verdict: not bloat wholesale; two identifiable pockets of
over-capability on an otherwise weight-justified client.

---

## API-churn signals (evidence the shape is still moving)

Not the core question, but they show the surface is not yet settled:

1. **`MQTTPublisher` / `client.publisher()` — specified, then deleted,
   ADR not updated.** Decision 0064 §5 (lines 70-80, 119-121) defines
   an `MQTTPublisher` topic-binder helper as public API. It is absent
   from `__all__` (`__init__.py`:25), from `src/`, and from the docs.
   The break is legal under 0092, but 0064 was never annotated —
   a reader trusting the ADR is misled.
2. **The flagship starter example is broken against the current API.**
   Sister-repo `ChuMicro-Workspace-Template/projects/example_sensor/app.py`
   constructs `MQTTClient(socket_factory=socket_factory, ...)` — a kwarg
   that **no longer exists** (it is `connector_factory=` now, per
   Decisions 0081/0093) — and its `_make_socket_factory` returns a
   *blocking* fully-connected `tcp_client_socket`, the exact synchronous
   anti-pattern Decision 0081 killed. The most-visible consumer of the
   library would fail at construction. (Read-only finding; fix belongs
   to the template repo.)

These two are the concrete "the API moved and consumers didn't follow"
data points behind the fitness question.

---

## The three biggest API mistakes (ranked) + better shapes

### #1 — `publish()`/`subscribe()` raise before CONNECTED, with no pre-connect queue

The async-connect decision (correct) leaks its consequence into every
caller: all four in-repo consumers guard state or drive-until-connected,
and the guide has to teach the on_connect workaround. Evidence:
client.py:793/887; demos/mqtt_pub_sub/app.py:106; examples/telemetry.py:118;
example_sensor HeartbeatPublisher; guide.md:24-35.

Better shape:
```python
def publish(self, topic, payload, *, qos=0, retain=False,
            when_disconnected="queue"):   # "queue"(default) | "drop" | "raise"
```
`"queue"` = bounded buffer flushed on CONNACK and on each self-heal
reconnect. Deletes the on_connect-dance from every consumer; makes the
common path free and the exceptional path opt-in.

### #2 — Overbuilt three-tier decoder (the intact drain mode)

~350 lines / two drain state machines for a payload profile the library
itself documents as almost always steady-tier; only tier 3 delivers the
anti-OOM guarantee. Evidence: _wire.py:459-489, 727-824, 826-865;
guide.md:343-357.

Better shape: two tiers — steady parse, oversize→policy via rolling
discard. Drop `_DRAIN_INTACT`. Users needing intact >256 B set
`rx_buffer_size` (docs already say so). Keep the intact tier only if
transient-4 KB-without-persistent-RAM is a stated requirement — and then
name it as the deliberate cost it is.

### #3 — Three inbound surfaces; the pattern-handler router is the redundant one

`on_message` + `next_message` is the deliberate, good Decision-0089
pair. `add_pattern_handler`/`remove_pattern_handler` is a third
in-library topic router used once, trivially, in the whole repo, with a
public `topic_matches()` already available. Evidence: client.py:1011-1042;
_wire.py:171-205; only user is demo app.py:121.

Better shape: keep `on_message` + `next_message`; delete the
pattern-handler pair; point routing-needing users at the public
`topic_matches(topic, pattern)`. Removes API surface, the
not-auto-prefixed caveat, and part of the "pick one surface" load.

---

## Ranked recommendation list

1. **Fix publish-before-connected (#1).** Highest ergonomic payoff;
   removes ceremony from 100% of observed consumers. Add a bounded
   pre-connect queue + `when_disconnected=` policy; stop raising by
   default.
2. **Cut the intact decoder tier (#2).** ~150 lines and a whole drain
   mode gone; anti-OOM guarantee (tier 3) retained; documented sizing
   guidance already supports the two-tier model.
3. **Delete the pattern-handler router (#3).** Converge inbound on the
   two blessed 0089 surfaces + public `topic_matches()`.
4. **Resolve the session-resume half-build (§9).** Either honor CONNACK
   session-present (gate subscription replay on it) or drop
   `clean_session=False` and document clean-only. A knob that does not
   do what it says is worse than an absent one.
5. **Soften backpressure for QoS 0 (§3).** Drop-oldest or boolean return
   for fire-and-forget; reserve the raise for QoS 1.
6. **Housekeeping (not shape):** annotate Decision 0064 that
   `MQTTPublisher` was removed; the template repo's `example_sensor`
   must migrate `socket_factory=`→`connector_factory=` and stop building
   a blocking socket; add one guide sentence on keepalive vs deep-sleep.

Net: the connect/self-heal core is genuinely best-in-class for this
device class and worth its weight. The client is not the wrong *kind* of
API — the reactive runner-shaped client is the only shape that fits the
async-ban + cooperative-runner constraints, and the comparanda cannot be
adopted wholesale. It is over-shaped in two spots (intact tier, pattern
router) and under-smoothed in one high-traffic spot (publish before
connected), and one advertised capability (session resume) is
half-wired. Fixing #1-#4 would remove ~300-400 lines and the ceremony
from every consumer while losing no capability any consumer uses.
