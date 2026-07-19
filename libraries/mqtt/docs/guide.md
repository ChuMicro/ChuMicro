# User Guide

## Overview

`chumicro-mqtt` is a non-blocking MQTT 3.1.1 client (QoS 0 + 1) for CircuitPython, MicroPython, and CPython.  Built on `chumicro-sockets` and `chumicro-timing`; no `async`, no threads, no blocking on network I/O.  An LED keeps blinking on the same board while a publish or subscribe is in flight, because `client.check(now_ms)` / `client.handle(now_ms)` do at most one tick of work per call.

QoS 2 raises `UnsupportedQoSError`.  Last-will, retained messages, wildcard topic matching, and a structured oversized-message policy are built in.

## Getting started with generators

The receive-stream surface reads inbound messages as a linear loop: `message = yield from client.next_message()` waits for the next message, acts on it, and loops until the client parks for good.  Register the client (it does the socket I/O each tick) and the consumer generator side by side.

```python
from chumicro_mqtt import MQTTClient
from chumicro_runner import Runner
from chumicro_sockets.sockets_factory import fixed_connector_factory

client = MQTTClient(
    transport_factory=fixed_connector_factory("broker.example.com", 1883),
    client_id="sensor-1",
)
client.subscribe("commands/+")
client.connect()


def consume():
    while True:
        message = yield from client.next_message()   # InboundPublish
        if message is None:
            break                                    # client parked for good
        print(message.topic, message.payload)


runner = Runner()
runner.add(client)
handle = runner.add_generator(consume())
runner.run_until(handle)
```

`MQTTClient.from_config(config, radio=...)` wires the same `fixed_connector_factory` for you from `mqtt.broker.host` / `mqtt.broker.port` and derives a per-device `client_id`.  The first `next_message()` call switches inbound delivery from the `on_message` callback to a bounded drop-oldest queue the generator drains; pick one inbound surface per client.  See `examples/receive_stream.py`.

## Getting started with a service

Reach for the callback service when you fan out across topics with `on_message` and `topic_matches`, or when you drive the client from your own tick loop.

```python
from chumicro_timing import ticks_ms
from chumicro_mqtt import MQTTClient

# The transport factory dials the broker for you (non-blocking, one
# connect phase per tick) and rebuilds the socket after a wifi drop.
# On CircuitPython pass `radio=wifi.radio` to `from_config`; on
# MicroPython / CPython the kwarg is ignored.
client = MQTTClient.from_config(
    {"mqtt.broker.host": "broker.example.com", "mqtt.broker.port": 1883},
    radio=None,
)

client.on_message = lambda topic, payload: print(topic, payload)

# subscribe() is a declaration — call it before connect().  The client
# records the topic and sends the SUBSCRIBE on the first CONNACK, and
# replays it after any self-heal reconnect.  Declaring in on_connect is
# equally valid, just no longer required.
client.subscribe("commands/+")
client.connect()

# publish() can be called straight away: before CONNECTED it buffers in
# a small pre-connect queue and flushes on CONNACK (the default
# when_disconnected="queue" policy — no state guard needed).
client.publish("status/online", b"true", retain=True)

# Drive from your tick loop — no threads, no async.
while True:
    now = ticks_ms()
    if client.check(now):
        client.handle(now)
```

Build your client at startup. The first `MQTTClient` reference imports the client module, so let that one-time cost land on a fresh heap.

`connect()` queues the CONNECT packet; the first few `handle()` calls drive it through CONNECTING → CONNECTED.  `publish()` called before then buffers into a bounded pre-connect queue and flushes on CONNACK — the default `when_disconnected="queue"` policy (`"raise"` restores the raise-if-not-connected behavior).  `subscribe()` and `unsubscribe()` are declarations valid in any state: call them before `connect()` and the first CONNACK puts them on the wire (a self-heal reconnect replays them). Calling `subscribe()` while already CONNECTED still sends immediately, and placing it in `on_connect` is equally valid — just no longer required.

`MQTTClient` actually enforces non-blocking mode on every socket it acquires (force-`setblocking(False)`), so the explicit `sock.setblocking(False)` line above is belt-and-suspenders.  Don't omit it — MP plain TCP defaults to blocking, and a blocking `recv` against a silent peer (broker that's hung mid-handshake, network blackholing returning packets) stalls the tick loop indefinitely on Pi Pico W RP2.  Bench-tested with a stalled TCP listener: recv was still blocked at the 3-minute mark, with no TCP keepalive timeout fired within that window.  Whole-app freeze, not a recoverable hiccup.

## Publishing

```python
# QoS 0 — fire-and-forget
client.publish("sensors/temp", b"21.5", qos=0)

# QoS 1 — at-least-once with PUBACK round-trip
def acked(topic, payload):
    print("publish acked:", topic, payload)

client.publish("sensors/temp", b"21.5", qos=1, on_publish=acked)

# Retained
client.publish("status/online", b"true", retain=True)
```

The `on_publish=` callback is invoked as `on_publish(topic, payload_bytes)` — the same topic and payload passed to `publish()`.  For QoS 1 it fires once the broker's PUBACK lands; for QoS 0 it fires once the bytes hit the wire.  `chumicro-mqtt` tracks every in-flight QoS-1 packet by `packet_id` so re-deliveries (from `publish_retry_max`-driven retransmits) don't double-fire callbacks.

### Publishing before connected

Connect is asynchronous, so `publish()` can be called while the client is still coming up (or during a self-heal outage).  The `when_disconnected=` constructor policy governs what happens:

| `when_disconnected` | Before CONNECTED |
|---|---|
| `"queue"` (default) | Buffer in a bounded pre-connect queue (`pre_connect_queue_size`, default 8), drained on CONNACK in receipt order ahead of any publish `on_connect` issues.  A full queue raises `MQTTBackpressureError` — the same signal a full tx queue gives. |
| `"raise"` | Raise `MQTTError` immediately — the strict "must be connected" behavior. |

Queued publishes preserve their `qos` / `retain` and fire their `on_publish` callback when they eventually reach the wire.  `subscribe()` / `unsubscribe()` don't use this queue — they are declarations recorded in the subscription set and (re)sent on CONNACK (see [Subscribing and routing](#subscribing-and-routing)).

## Subscribing and routing

`on_message(topic, payload)` is the catch-all callback:

```python
client.on_message = lambda topic, payload: print(topic, "=>", payload)
client.subscribe("commands/+")             # MQTT wildcard
client.subscribe("status/#", qos=1)        # multi-level wildcard
```

`subscribe()` is a declaration valid in any state — call it before `connect()`, inside `on_connect`, or any time while CONNECTED. It records the topic in the client's subscription set; the SUBSCRIBE goes on the wire immediately when already CONNECTED, otherwise on the first CONNACK. Either way the `on_subscribe(topic, granted_qos)` callback fires once, on the SUBACK that grants the topic. A self-heal reconnect replays the set to restore the inbound stream, without re-firing `on_subscribe`. `unsubscribe()` mirrors this: it retracts the declaration in any state and sends the UNSUBSCRIBE when CONNECTED.

For structured routing, branch inside `on_message` with the public `topic_matches(topic, pattern)` matcher — `+` matches one segment, `#` matches the trailing tail:

```python
from chumicro_mqtt import topic_matches

def route(topic, payload):
    if topic_matches(topic, "commands/set"):
        apply_setting(payload)
    elif topic_matches(topic, "commands/reset"):
        reset_now()

client.on_message = route
client.subscribe("commands/+")             # one wire-level subscribe covers both
```

`on_message` + `topic_matches` and `next_message()` (below) are the two inbound surfaces — pick one per client.

### Receive stream (`next_message`)

For a single-subscription consumer, `next_message()` reads inbound messages as a linear generator loop instead of a callback — register the client (it does the I/O each tick) and the consumer generator side by side:

```python
runner.add(client)

def consume(client):
    while True:
        message = yield from client.next_message()   # InboundPublish
        if message is None:
            break                                    # client parked for good
        act_on(message.topic, message.payload)

runner.add_generator(consume(client))
```

The first `next_message()` call switches inbound data delivery from the `on_message` callback to a bounded queue the generator drains (16 messages, drop-oldest — a slow consumer loses the oldest messages rather than growing the heap).  Lifecycle callbacks (`on_connect`, `on_disconnect`, `on_oversized`) keep firing either way.  Pick one inbound surface per client: the stream for a linear single-topic consumer, `on_message` for multi-topic fan-out.  See `examples/receive_stream.py`.

## Last-will

Configured at construction time; the broker publishes the will when the connection is uncleanly dropped (network loss, device hard-reset, etc.):

```python
client = MQTTClient(
    sock,
    client_id="my-thing",
    will_topic="status/online",
    will_message=b"false",
    will_qos=1,
    will_retain=True,
)
```

A clean `client.disconnect()` suppresses the will.

To change the will after construction (e.g. swap "online" for "offline" before a graceful shutdown), use `set_will`:

```python
client.set_will("status/online", b"offline", qos=1, retain=True)
# Next CONNECT (or self-heal reconnect) carries the new will.
```

`set_will(topic=None)` disables the will entirely.  The change applies to the next CONNECT packet — the broker already has the will from the in-flight session and can't be modified mid-connection.

## TLS connections

Pass an `ssl_context=` to `from_config` and the auto-built transport
factory dials with `tls=True`:

```python
from chumicro_sockets import ssl_context_with_ca

with open("/ca.pem", "rb") as handle:
    ca_pem = handle.read()
ssl_context = ssl_context_with_ca(ca_pem)         # CERT_REQUIRED by default
client = MQTTClient.from_config(
    {"mqtt.broker.host": "broker.example.com", "mqtt.broker.port": 8883},
    ssl_context=ssl_context,
    radio=wifi.radio,                              # CP only
)
```

A few platform realities:

* On MP rp2 (Pi Pico W), `chumicro-sockets` automatically converts PEM to DER for `load_verify_locations` — the rp2 firmware ships without `MBEDTLS_PEM_PARSE_C`.
* **The TLS handshake blocks the whole reactor, not just this client.** It runs synchronously inside `wrap_socket(...)`, so for its full duration every other runner-registered service — a sensor sample, a watchdog feed, an LED heartbeat — gets no tick. Bench-tested against `test.mosquitto.org:8883`: 2–3 ms on Lolin S2 CP and 10–11 ms on Pi Pico W CP on a good link, but tens of ms — or seconds against a slow or unreachable broker — on a high-latency uplink. Connect before you start time-critical services, or budget for the stall.
* **DNS resolution also blocks the reactor.** The connector's `awaiting_dns` phase calls a synchronous `getaddrinfo`, which hangs for the resolver's own timeout when DNS is slow or down. Pre-resolve and pass an IP if a stall there is unacceptable.
* For server-side TLS handshake heap sizes per board, see the `chumicro-http-server` guide's TLS-server table.

## Wifi-drop self-heal

Pass a `transport_factory` callable instead of a bare socket and the client will rebuild its socket automatically after a wifi-drop / socket-death. The TCP-connect phase advances one tick at a time, but DNS and the TLS handshake still block the reactor for their duration (see the TLS-connections platform realities above):

```python
from chumicro_sockets import connector

def make_connector():
    return connector("broker.example.com", 1883, radio=wifi.radio)

client = MQTTClient(transport_factory=make_connector, client_id="my-thing")
client.connect()
# … socket dies mid-session …
# Next handle() after FAILED enters AWAITING_TRANSPORT; subsequent ticks
# drive a fresh connector through DNS / TCP / TLS one phase per tick.
```

Reconnects are paced by exponential backoff: the first retry after a fresh failure fires immediately, then each subsequent attempt doubles its wait from 1 s up to a 60 s ceiling, so a persistent outage doesn't storm the broker or drain the battery. A successful `CONNACK` resets the schedule. Rejections that reconnecting can't fix — `CONNACK` return codes 1, 2, 4, and 5 (unacceptable protocol version, identifier rejected, bad username/password, not authorized) — latch the client `FAILED` and stop self-heal until the next explicit `connect()`. Return code 3 (server unavailable) stays transient and keeps retrying. A `SUBACK` rejection (granted QoS `0x80`) evicts that filter from the client's subscription set before it faults, so the reconnect's subscription replay doesn't re-issue the rejected topic and re-earn the same rejection forever.

Without a factory the client transitions to `FAILED` on socket death and stays there until the caller manually tears down + reconstructs.

The factory is also the recommended way to wire up the **initial** connect: the runner is not blocked for the round-trip, and the same code path serves both initial-connect and reconnect.  `MQTTClient.from_config(...)` builds the connector factory for you from `mqtt.broker.host` / `mqtt.broker.port` (and `ssl_context=` for TLS).

### `connect()` is an intent; `hold()` is its mate

`connect()` means "be connected", acting on it now.  It is safe to call in any state and does the least-surprising thing for the one it finds:

- **DISCONNECTED** — starts the connect sequence (as above).
- **FAILED** — reconnects **immediately**, short-circuiting any remaining self-heal backoff.  It fires the same reconnect the timer would — queued / in-flight / clean-session fate is identical — it just skips the wait.  Call it whenever you KNOW the link is back rather than letting the client sit out residual backoff.
- **CONNECTED / CONNECTING / AWAITING_TRANSPORT** — idempotent no-op.  The intent is already being satisfied, so nothing is disturbed and no second dial races the one in flight.

So re-issuing `mqtt.connect()` on wifi-recovery is not just safe, it is the recommended wiring: it dials the moment the link returns instead of waiting out the backoff.

The symmetric primitive is **`hold()`**.  When your app KNOWS the link is down — its wifi service just reported the radio dropped — call `mqtt.hold()` to suspend the self-heal timer so it stops dialing into a dead radio (on ESP-IDF those doomed dials can even contend with the radio's own re-association).  While held, the client stays `FAILED` with `last_error` intact, publishes still buffer per `when_disconnected`, and the runner parks cleanly instead of spinning on retries.  `connect()` releases the hold and dials.

`MQTTClient` never watches wifi itself — it runs on hosts with no radio, and it stays transport-agnostic — so the app that owns both services composes them.  The canonical `chumicro-wifi` wiring is one line each way:

```python
from chumicro_wifi import WifiState

def on_wifi_state(old, new):
    if new == WifiState.DISCONNECTED:
        mqtt.hold()       # link is down: stop dialing a dead radio
    elif new == WifiState.CONNECTED:
        mqtt.connect()    # link is back: reconnect now (also clears the hold)

wifi.on_state_change(on_wifi_state)
```

You can still wire the callback to nothing and let self-heal reconnect on its own — `hold()` / `connect()` only *tighten* the timing when the app has better information than the timer does.

What happens to publishes issued during the outage depends on the state the client is in when `publish()` runs, and this is worth understanding because it decides which publishes survive a wifi drop:

- Issued while still `CONNECTED` — the link is physically down but the client hasn't detected it yet (detection lags by up to `ack_timeout_seconds`, longer if a blocked reactor starves its ticks) — a QoS-1 publish opens an in-flight entry sent on the doomed socket.  It is never acked, and with the default `clean_session=True` the self-heal reconnect resets the in-flight table, so that publish is **dropped**.  This is ordinary clean-session semantics (the broker forgets the session too); set `clean_session=False` for a persistent broker to have these redelivered with `DUP=1` instead.
- Issued once the client is `FAILED` / `AWAITING_TRANSPORT` — after the drop is detected — the publish buffers into the bounded pre-connect queue and **flushes** on the reconnect `CONNACK`, oldest first.

So a wifi outage can lose the last publish or two that raced the drop-detection window while flushing everything queued after it — not a bug, but a reason to keep the reactor tick-healthy (a substrate call that blocks the loop widens the raced-and-dropped window) and to choose `clean_session` deliberately.

## Bring your own transport

`MQTTClient` does not care which library produces its socket.  Any object exposing the four-method contract works:

| Method | Contract |
|---|---|
| `recv_into(buffer, nbytes) -> int` | Reads up to `nbytes` into `buffer` (a `memoryview`).  Raises `OSError(EAGAIN \| EWOULDBLOCK)` on no data, returns 0 on peer-close, otherwise returns bytes written. |
| `send(payload) -> int` | Sends `payload` (a `bytes`).  Raises `OSError(EAGAIN \| EWOULDBLOCK)` when the send buffer is full, otherwise returns bytes sent (may be partial). |
| `close() -> None` | Releases the connection. |
| `setblocking(flag) -> None` | Best-effort.  Absence is tolerated. |

The socket a `chumicro_sockets.connector` leaves on `.socket` at `ready` is one valid producer.  Stdlib `socket.socket` after `setblocking(False)` is another.  An upstream-library wrapper or a hand-rolled fake works the same way:

```python
# Example: stdlib socket on CPython for a test or desktop demo.
import socket

sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.connect(("broker.example.com", 1883))
sock.setblocking(False)
client = MQTTClient(sock, client_id="desktop-demo")
```

This pre-built-socket form is the right shape for one-shot scripts or tests where the caller already owns the connect.  The runner-shape (no synchronous network I/O from a tick) only matters when the client lives inside a runner — and there the `transport_factory` form above is what you want.

The library has no `isinstance` checks against `chumicro_sockets` types — the contract is the four methods above.  Runtime errors surface at first call, not at construction time, so a misshaped object fails on the first `recv_into` / `send` rather than silently misbehaving.

If you supply your own transport and never want `chumicro_sockets` to land on the device, add a module-level constant to your entrypoint and the chumicro-workspace deployer will filter the default factory out of the import graph:

```python
# code.py / app.py
__chumicro_skip_factories__ = ("sockets_factory",)
```

The constant accepts a family form (the bare stem, matches every `chumicro_*.sockets_factory`) or an exact dotted path (`chumicro_sockets.sockets_factory`).  An unmatched entry fails the deploy with a typo message rather than silently shipping the default.  Calling `MQTTClient.from_config(...)` when `chumicro_sockets.sockets_factory` is missing (skipped at deploy time, or not installed by `circup` / `mip`) raises `RuntimeError` naming the bypass kwarg, so the failure mode is loud rather than mysterious.

For the full single-library adoption recipe — your transport, your `ticks=`, the runner-less drive loop, and host tests with no board — see [Standalone integration](https://github.com/ChuMicro/ChuMicro/blob/main/docs/contributing/standalone-integration.md).

## Tuning for tick-latency vs throughput

`handle()` does exactly one `recv_into` and one packet `send` per tick, so each call yields back to the runner after a bounded slice of socket work.  (On ticks that dispatched inbound QoS-1 publishes there is one extra send: the tick's PUBACKs coalesce into a single batch flushed ahead of — and without consuming — the packet budget, so the ack rate always keeps up with the inbound rate.  If the socket can't take the batch, the client stops reading until it lands; the unread bytes throttle the broker through the TCP window.)  Three constructor knobs let you tune the trade-off:

| Knob | Default | What it bounds |
|---|---|---|
| `recv_budget_per_tick` | `1024` (bytes) | Cap on the single per-tick `recv_into` call — the inbound pacing lever.  It bounds tick latency on a multi-KB inbound PUBLISH (the payload arrives across several ticks instead of monopolizing one), how many packets one tick can dispatch, and the size of the per-tick PUBACK batch.  Raise for faster ingestion at the cost of per-tick latency. |
| `max_tx_queue_size` | `20` packets | Hard cap on pending outbound packets.  Sized for the runner-shaped sensor profile (publish every N seconds; queue stays near zero).  Appending past the cap raises `MQTTBackpressureError`; protocol-internal traffic (PUBACK responses, retransmits, PINGREQ) bypasses the cap so QoS-1 / keepalive contracts hold.  Failed QoS-1 publishes roll back the `packet_id` allocation cleanly so the id pool isn't leaked on backpressure.  Raise for bursty publishers; each slot pins ~8 bytes long-lived on MP / CP. |
| `send_timeout_seconds` | inherits `ack_timeout_seconds` (5 s) | Maximum time the socket can stay non-writable with a packet queued before the client transitions to `FAILED` and self-heal fires.  Re-arms on every successful send -- a steady drip never trips it, only a stalled socket does.  Catches NAT-style silent-drops on the outbound path that would otherwise let the queue grow until `MQTTBackpressureError`. |

```python
client = MQTTClient(
    sock,
    client_id="my-thing",
    recv_budget_per_tick=4096,             # faster big-blob ingestion per syscall
    max_tx_queue_size=100,                 # bursty publisher
    send_timeout_seconds=10.0,             # longer outbound-stall tolerance
)
```

## Two-tier inbound size model

`chumicro-mqtt` distinguishes two tiers for inbound PUBLISH handling so a normal sensor reading is delivered intact while a hostile 1 MB blob stays heap-bounded on a 256 KB-RAM board:

| Tier | Condition | What happens |
|---|---|---|
| **Steady** | `total_length ≤ rx_buffer_size` (default 256 B) | Parsed inline from the pre-allocated RX buffer; no per-message allocation.  `on_message` fires with the full payload. |
| **Oversized** | `total_length > rx_buffer_size` | `WhenOversized` policy applies (see below).  Payload drains via rolling discard through the RX buffer — no payload-sized heap allocation, so the heap cost is constant regardless of the inbound size. |

To receive a larger PUBLISH intact, size `rx_buffer_size` up to cover it (a few hundred bytes for sensor readings, a few KB for JSON config blobs).  Anything larger than the steady buffer is oversized and its payload is dropped — the anti-OOM guarantee.

## Oversized-message policy

`rx_buffer_size` is the steady/oversized boundary (default 256 B).  An inbound PUBLISH whose total wire size exceeds it triggers `when_oversized`:

```python
from chumicro_mqtt import MQTTClient, WhenOversized

client = MQTTClient(
    sock,
    client_id="my-thing",
    rx_buffer_size=4096,                             # deliver up to 4 KB intact
    when_oversized=WhenOversized.DROP_WITH_EVENT,   # default
)
```

Three policies:

| `WhenOversized` | Behavior |
|---|---|
| `DROP_SILENT` | Drain via rolling discard, no event, stay connected. |
| `DROP_WITH_EVENT` (default) | Drain via rolling discard, fire `on_oversized(reported_length, topic)` for telemetry, stay connected.  `topic` is `None` when the topic itself was too long to parse from the RX buffer. |
| `DISCONNECT` | Raise `MQTTProtocolError`, transition to `FAILED` — appropriate when oversized inputs indicate a misconfiguration.  Socket-factory self-heal kicks in if configured. |

No payload bytes survive the oversized tier — the bytes drain through the RX buffer without any payload-sized allocation.  Diagnostic information (`reported_length` + `topic`) is enough for application-side reaction; if you need the actual bytes, raise `rx_buffer_size` so the message parses inline in the steady tier instead.

## Backpressure

When `max_tx_queue_size` is reached, user-initiated publish/subscribe calls raise `MQTTBackpressureError`:

```python
from chumicro_mqtt import MQTTBackpressureError

try:
    client.publish("burst/data", payload, qos=1)
except MQTTBackpressureError:
    # Drain via handle() and retry next tick.
    pass
```

Internally the queue carries some headroom over `max_tx_queue_size` (~64 packets) so QoS-1 retries and protocol-internal traffic don't trigger the cap.

## State machine

```python
from chumicro_mqtt import ProtocolState

if client.state == ProtocolState.CONNECTED:
    client.publish(...)
elif client.state == ProtocolState.FAILED:
    log.warning("mqtt failed; reconnecting in 30 s")
```

Five states: `DISCONNECTED`, `AWAITING_TRANSPORT`, `CONNECTING`, `CONNECTED`, `FAILED`.  `AWAITING_TRANSPORT` appears only when a `transport_factory` is driving the transport up (DNS / TCP / TLS) before the MQTT CONNECT goes out; a client built with a ready socket skips straight to `CONNECTING`.  `disconnect()` is synchronous (DISCONNECT packet + close), so there is no intermediate "disconnecting" state to observe.

## Memory notes

The client actively manages its memory footprint with four caps tunable at construction time:

| Cap | Default | What it bounds |
|---|---|---|
| `recv_budget_per_tick` | `1024` bytes | Per-tick read ceiling — see [Tuning](#tuning-for-tick-latency-vs-throughput). |
| `rx_buffer_size` | `256` bytes | Pre-allocated steady-state RX buffer, and the steady/oversized boundary.  Inbound PUBLISHes at or below this size parse inline and deliver intact with no further allocation; above it, the [`WhenOversized` policy](#oversized-message-policy) applies and the payload drains without a payload-sized allocation. |
| `pre_connect_queue_size` | `8` packets | Bound on the pre-connect publish queue (the `when_disconnected="queue"` buffer) — see [Publishing](#publishing). |
| `max_tx_queue_size` | `20` packets | Outbound packet queue cap — see [Backpressure](#backpressure). |

The QoS-1 in-flight table (keyed by `packet_id`, one entry per outstanding QoS-1 PUBLISH waiting for PUBACK) grows with your usage — it has no hard cap.  On memory-tight boards, keep `rx_buffer_size` at your actual largest expected broker payload — anything bigger routes through the oversized tier where it can't blow the heap.

### What fits in the 256 B steady-state buffer

The decoder sees the whole MQTT packet, not just the payload — `1` (fixed byte) `+ 1–2` (varlen) `+ 2` (topic-length field) `+ len(topic)` `+ 0/2` (packet_id when QoS 1) `+ len(payload)`.  At a glance:

| Use case | Wire size | Tier |
|---|---|---|
| Plain sensor reading — `home/livingroom/temp` `21.3` | ~30 B | steady |
| Small JSON sensor — `home/livingroom/sensor` `{"t":21.3,"h":45}` | ~45 B | steady |
| Device-prefixed status — `livingRoom/mainLightSwitch/online` `false` | ~45 B | steady |
| Multi-field JSON — `home/livingroom/env` `{"temp":21.3,"hum":45,"pressure":1013,"co2":412}` | ~75 B | steady |
| Verbose JSON sensor (~150 B payload, 20 B topic) | ~175 B | steady (default rx) |
| HomeAssistant discovery (`homeassistant/.../config` + ~300 B JSON) | ~350 B | steady at `rx_buffer_size=512` |
| AWS IoT Core shadow `update/accepted` (~250–600 B JSON) | ~300–700 B | steady at `rx_buffer_size=1024` |

So **plain sensor data, small-to-medium JSON readings (payload ≤ ~200 B on a ≤ 40 B topic), and device-prefixed status messages all parse inline at the 256 B default with zero per-message allocation.**  Structured-config workloads — HomeAssistant discovery descriptors, AWS IoT shadow documents, MQTT-SN gateway state — deliver intact once `rx_buffer_size` is sized to cover them: the buffer is allocated once at construction, not per message.  If your typical PUBLISH is consistently above ~250 B, bump `rx_buffer_size` (e.g. `512` or `1024`) so it stays in the steady tier; anything above the buffer routes through the oversized tier and its payload is dropped.

## Platform notes

| Runtime | TCP | TLS | Notes |
|---|---|---|---|
| CPython | ✅ | ✅ | Reference runtime — works against any broker. |
| MicroPython | ✅ | ✅ | mbedTLS PEM→DER conversion on rp2 (handled by `chumicro-sockets`). |
| CircuitPython | ✅ (requires `radio=wifi.radio`) | ✅ | TLS handshake is synchronous — bench-tested under 15 ms on both Lolin S2 and Pi Pico W against `test.mosquitto.org:8883` over a good wifi link. |

`MQTTClient` enforces non-blocking mode on every socket it acquires.  MicroPython plain TCP defaults to blocking, and a blocking `recv` against a silent peer on a Pi Pico W stalls the tick loop indefinitely — set `sock.setblocking(False)` explicitly so the contract is visible at the call site.

## Examples

| Example | What it shows |
|---|---|
| [`examples/telemetry.py`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/mqtt/examples/telemetry.py) | Periodic QoS-1 publish on a real CP/MP board.  Brings wifi up, connects to a broker, subscribes to a command topic, publishes a synthetic reading every N seconds while an LED-blink counter verifies the publish never blocks waiting for PUBACK.  Cross-runtime (CP + MP). |
| [`examples/bench.py`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/mqtt/examples/bench.py) | Self-driving validation bench — deploy + watch serial.  Runs the scenarios (steady inline, oversized drain, oversize-topic, QoS-1 round-trip, sustained burst, keepalive) against a real broker and prints a pass/fail summary with per-scenario heap deltas + tick latency.  Companion [`examples/bench_host.py`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/mqtt/examples/bench_host.py) captures the verdict from the broker and can publish a 64 KB hostile payload for extra oversized-tier stress (host-side, needs `pip install paho-mqtt`). |

---

<div class="chumicro-footer" markdown>

[← Home](index.md)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/mqtt) · \
[PyPI](https://pypi.org/project/chumicro-mqtt/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
