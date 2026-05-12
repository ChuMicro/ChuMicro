# User Guide

## Overview

`chumicro-mqtt` is a non-blocking MQTT 3.1.1 client (QoS 0 + 1) for CircuitPython, MicroPython, and CPython.  Built on `chumicro-sockets` and `chumicro-timing`; no `async`, no threads, no blocking on network I/O.  An LED keeps blinking on the same board while a publish or subscribe is in flight, because `client.check(now_ms)` / `client.handle(now_ms)` do at most one tick of work per call.

QoS 2 raises `UnsupportedQoSError`.  Last-will, retained messages, pattern-routed handlers, and a structured oversized-message policy are built in.

## Getting started

```python
from chumicro_sockets import tcp_client_socket
from chumicro_timing import ticks_ms
from chumicro_mqtt import MQTTClient

# On CircuitPython pass `radio=wifi.radio` here; on MicroPython / CPython the kwarg is ignored.
sock = tcp_client_socket("broker.example.com", 1883, radio=None)
sock.setblocking(False)                     # MP defaults to blocking — enforce non-blocking
client = MQTTClient(sock, client_id="my-thing", keep_alive_seconds=60)

client.on_message = lambda topic, payload: print(topic, payload)
client.connect()
client.subscribe("commands/+")

# Drive from your tick loop — no threads, no async.
while True:
    now = ticks_ms()
    if client.check(now):
        client.handle(now)
```

`connect()` queues the CONNECT packet; the first few `handle()` calls drive it through CONNECTING → CONNECTED.  Subscribe / publish before or after `connect()` — both are queued either way and flushed once the broker session is up.

`MQTTClient` actually enforces non-blocking mode on every socket it acquires (force-`setblocking(False)`), so the explicit `sock.setblocking(False)` line above is belt-and-suspenders.  Don't omit it — MP plain TCP defaults to blocking, and a blocking `recv` against a silent peer (broker that's hung mid-handshake, network blackholing returning packets) stalls the tick loop indefinitely on Pi Pico W RP2.  Bench-tested with a stalled TCP listener: recv was still blocked at the 3-minute mark, with no TCP keepalive timeout fired within that window.  Whole-app freeze, not a recoverable hiccup.

## Publishing

```python
# QoS 0 — fire-and-forget
client.publish("sensors/temp", b"21.5", qos=0)

# QoS 1 — at-least-once with PUBACK round-trip
def acked(packet_id):
    print("publish acked, id =", packet_id)

client.publish("sensors/temp", b"21.5", qos=1, on_publish=acked)

# Retained
client.publish("status/online", b"true", retain=True)
```

The `on_publish=` callback fires once per QoS-1 publish, after the broker's PUBACK lands.  `chumicro-mqtt` tracks every in-flight QoS-1 packet by `packet_id` so re-deliveries (from `publish_retry_max`-driven retransmits) don't double-fire callbacks.

## Subscribing and routing

`on_message(topic, payload)` is the catch-all callback:

```python
client.on_message = lambda topic, payload: print(topic, "=>", payload)
client.subscribe("commands/+")             # MQTT wildcard
client.subscribe("status/#", qos=1)        # multi-level wildcard
```

For more structured routing, `add_pattern_handler(pattern, handler)` runs handlers per topic match before `on_message`:

```python
def handle_cmd_set(topic, payload):
    # `topic` is the actual topic, e.g. "commands/set"
    apply_setting(payload)

def handle_cmd_reset(topic, payload):
    reset_now()

client.add_pattern_handler("commands/set", handle_cmd_set)
client.add_pattern_handler("commands/reset", handle_cmd_reset)
client.subscribe("commands/+")             # one wire-level subscribe covers both
```

Pattern handlers honor MQTT wildcard semantics (`+` for one segment, `#` for the trailing tail).

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

## TLS connections

Build the socket with `tls_client_socket` instead of `tcp_client_socket`:

```python
from chumicro_sockets import tls_client_socket, ssl_context_with_ca

with open("/ca.pem", "rb") as handle:
    ca_pem = handle.read()
ssl_context = ssl_context_with_ca(ca_pem)         # CERT_REQUIRED by default
sock = tls_client_socket(
    "broker.example.com", 8883,
    ssl_context=ssl_context,
    radio=wifi.radio,                              # CP only
)
sock.setblocking(False)
client = MQTTClient(sock, client_id="my-thing")
```

A few platform realities:

* On MP rp2 (Pi Pico W), `chumicro-sockets` automatically converts PEM to DER for `load_verify_locations` — the rp2 firmware ships without `MBEDTLS_PEM_PARSE_C`.
* The TLS handshake is synchronous inside `wrap_socket(...)` — bench-tested against `test.mosquitto.org:8883`, the listener stalls 2–3 ms on Lolin S2 CP and 10–11 ms on Pi Pico W CP for the full handshake.  Short on a good link; longer (tens of ms) on a high-latency uplink as TLS rounds-trip with the broker.
* For server-side TLS handshake heap sizes per board, see the `chumicro-http-server` guide's TLS-server table.

## Wifi-drop self-heal

Pass a `socket_factory` callable instead of a bare socket and the client will rebuild its socket automatically after a wifi-drop / socket-death:

```python
def make_socket():
    sock = tcp_client_socket("broker.example.com", 1883, radio=wifi.radio)
    sock.setblocking(False)
    return sock

client = MQTTClient(socket_factory=make_socket, client_id="my-thing")
client.connect()
# … socket dies mid-session …
# Next handle() after FAILED rebuilds the socket and re-issues connect().
```

Without a factory the client transitions to `FAILED` on socket death and stays there until the caller manually tears down + reconstructs.

## Bring your own transport

`MQTTClient` does not care which library produces its socket.  Any object exposing the four-method contract works:

| Method | Contract |
|---|---|
| `recv_into(buffer, nbytes) -> int` | Reads up to `nbytes` into `buffer` (a `memoryview`).  Raises `OSError(EAGAIN \| EWOULDBLOCK)` on no data, returns 0 on peer-close, otherwise returns bytes written. |
| `send(payload) -> int` | Sends `payload` (a `bytes`).  Raises `OSError(EAGAIN \| EWOULDBLOCK)` when the send buffer is full, otherwise returns bytes sent (may be partial). |
| `close() -> None` | Releases the connection. |
| `setblocking(flag) -> None` | Best-effort.  Absence is tolerated. |

`chumicro_sockets.tcp_client_socket` (and `tls_client_socket`) is one valid producer.  Stdlib `socket.socket` after `setblocking(False)` is another.  An upstream-library wrapper or a hand-rolled fake works the same way:

```python
# Example: stdlib socket on CPython for a test or desktop demo.
import socket

def make_socket():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect(("broker.example.com", 1883))
    sock.setblocking(False)
    return sock

client = MQTTClient(socket_factory=make_socket, client_id="desktop-demo")
```

The library has no `isinstance` checks against `chumicro_sockets` types — the contract is the four methods above.  Runtime errors surface at first call, not at construction time, so a misshaped object fails on the first `recv_into` / `send` rather than silently misbehaving.

If you supply your own transport and never want `chumicro_sockets` to land on the device, add a module-level constant to your entrypoint and the chumicro-workspace deployer will filter the default factory out of the import graph:

```python
# code.py / app.py
__chumicro_skip_factories__ = ("sockets_factory",)
```

The constant accepts a family form (the bare stem, matches every `chumicro_*.sockets_factory`) or an exact dotted path (`chumicro_mqtt.sockets_factory`).  An unmatched entry fails the deploy with a typo message rather than silently shipping the default.  Calling `MQTTClient.from_config(...)` when `chumicro_mqtt.sockets_factory` is missing — either skipped at deploy time or not installed by `circup` / `mip` — raises `RuntimeError` naming the bypass kwarg, so the failure mode is loud rather than mysterious.

## Tuning for tick-latency vs throughput

Two constructor knobs let you trade tick fairness for throughput:

| Knob | Default | What it bounds |
|---|---|---|
| `recv_budget_per_tick` | `1024` (bytes) | Soft cap on bytes drained from the socket in one `handle()` call.  Without it, a large inbound payload would monopolize the tick until fully drained — visibly stuttering a concurrent LED blink or sub-second control loop.  Raise for faster big-payload ingestion at the cost of LED smoothness. |
| `max_tx_queue_size` | `20` packets | Hard cap on pending outbound packets.  Sized for the runner-shaped sensor profile (publish every N seconds; queue stays near zero).  Appending past the cap raises `MQTTBackpressureError`; protocol-internal traffic (PUBACK responses, retransmits, PINGREQ) bypasses the cap so QoS-1 / keepalive contracts hold.  Failed QoS-1 publishes roll back the `packet_id` allocation cleanly so the id pool isn't leaked on backpressure.  Raise for bursty publishers; each slot pins ~8 bytes long-lived on MP / CP. |

```python
client = MQTTClient(
    sock,
    client_id="my-thing",
    recv_budget_per_tick=4096,             # faster big-blob ingestion
    max_tx_queue_size=100,                 # bursty publisher
)
```

Without `recv_budget_per_tick`, a "drain until EAGAIN" loop on a fat kernel recv buffer can blow tick latency past tens of milliseconds while it works through the backlog — long enough to skip a heartbeat on the same loop.

## Three-tier inbound size model

`chumicro-mqtt` distinguishes three tiers for inbound PUBLISH handling so a 4 KB sensor reading and a hostile 1 MB blob both stay heap-bounded on a 256 KB-RAM board:

| Tier | Condition | What happens |
|---|---|---|
| **Steady** | `total_length ≤ rx_buffer_size` (default 256 B) | Parsed inline from the pre-allocated RX buffer; no allocation.  `on_message` fires with the full payload. |
| **Intact** | `rx_buffer_size < total_length ≤ max_message_bytes` (default 8 KB) | One-shot `bytearray(payload_length)` allocated for this message; payload drains into it across multiple ticks; `on_message` fires with the full payload; buffer drops out of scope after delivery. |
| **Oversized** | `total_length > max_message_bytes` | `WhenOversized` policy applies (see below).  Payload drains via rolling discard through the RX buffer — no payload-sized heap allocation. |

In practice you tune `max_message_bytes` to your actual broker payload size (a few hundred bytes for sensor readings, a few KB for JSON config blobs, larger for OTA-image flows) and let the rest of the model take care of itself.

## Oversized-message policy

`max_message_bytes` is the cap for *intact* delivery (default 8 KB).  Messages larger than this trigger `when_oversized`:

```python
from chumicro_mqtt import MQTTClient, WhenOversized

client = MQTTClient(
    sock,
    client_id="my-thing",
    max_message_bytes=4096,                          # accept up to 4 KB intact
    when_oversized=WhenOversized.DROP_WITH_EVENT,   # default
)
```

Three policies:

| `WhenOversized` | Behavior |
|---|---|
| `DROP_SILENT` | Drain via rolling discard, no event, stay connected. |
| `DROP_WITH_EVENT` (default) | Drain via rolling discard, fire `on_oversized(reported_length, topic)` for telemetry, stay connected.  `topic` is `None` when the topic itself was too long to parse from the RX buffer. |
| `DISCONNECT` | Raise `MQTTProtocolError`, transition to `FAILED` — appropriate when oversized inputs indicate a misconfiguration.  Socket-factory self-heal kicks in if configured. |

No payload bytes survive the oversized tier — the bytes drain through the RX buffer without any payload-sized allocation.  Diagnostic information (`reported_length` + `topic`) is enough for application-side reaction; if you need the actual bytes, raise `max_message_bytes` so the message routes through the intact tier instead.

## Per-device topic prefixing

Set `root_topic` to enable automatic per-device prefixing — `publish` / `subscribe` / `unsubscribe` will prepend `<root_topic>/<client_id>/` to every topic:

```python
client = MQTTClient(
    sock,
    client_id="mainLightSwitch",
    root_topic="livingRoom",
)
client.connect()

client.publish("switchState", b"on")
# → publishes to "livingRoom/mainLightSwitch/switchState"

client.subscribe("commands/+")
# → subscribes to "livingRoom/mainLightSwitch/commands/+"
```

Use `publish_raw` / `subscribe_raw` / `unsubscribe_raw` for topics outside the per-device hierarchy (system topics, bridges):

```python
client.publish_raw("$SYS/broker/dead", b"true")
# → publishes verbatim to "$SYS/broker/dead", no prefix
```

The last-will follows the same pattern: `will_topic="online"` is prefixed; `will_topic_raw="$SYS/x/y"` is verbatim.  Pass at most one of them.

Inbound topics in `on_message` and pattern handlers (`add_pattern_handler`) are **not** prefix-stripped — what the broker put on the wire is what your callback gets.  Pattern handlers are also not auto-prefixed; pass the prefixed pattern if you want per-device-only routing.

## Repeated publishes — `MQTTPublisher`

For a topic you publish to repeatedly with the same QoS / retain settings, bind once:

```python
temperature = client.publisher("sensors/temperature", qos=1, retain=False)
temperature.publish(b"21.5")
temperature.publish("22.1")  # str auto-encoded as UTF-8
```

The bound topic resolves through `root_topic` exactly like `client.publish` — for raw publishing use `client.publish_raw` directly.

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

Four states: `DISCONNECTED`, `CONNECTING`, `CONNECTED`, `FAILED`.  `disconnect()` is synchronous (DISCONNECT packet + close), so there is no intermediate "disconnecting" state to observe.

## Memory notes

The client actively manages its memory footprint with four caps tunable at construction time:

| Cap | Default | What it bounds |
|---|---|---|
| `recv_budget_per_tick` | `1024` bytes | Per-tick read ceiling — see [Tuning](#tuning-for-tick-latency-vs-throughput). |
| `rx_buffer_size` | `256` bytes | Pre-allocated steady-state RX buffer.  Inbound PUBLISHes at or below this size parse inline with no further allocation. |
| `max_message_bytes` | `8 KB` | Intact-delivery cap.  Inbound PUBLISHes between `rx_buffer_size + 1` and this size allocate a one-shot buffer for the payload; above this size the [`WhenOversized` policy](#oversized-message-policy) applies and the payload drains without allocation. |
| `max_tx_queue_size` | `20` packets | Outbound packet queue cap — see [Backpressure](#backpressure). |

The QoS-1 in-flight table (keyed by `packet_id`, one entry per outstanding QoS-1 PUBLISH waiting for PUBACK) and the registered pattern-handler list grow with your usage — neither has a hard cap.  On memory-tight boards, set `max_message_bytes` to your actual largest expected broker payload — anything bigger routes through the oversized tier where it can't blow the heap.

### What fits in the 256 B steady-state buffer

The decoder sees the whole MQTT packet, not just the payload — `1` (fixed byte) `+ 1–2` (varlen) `+ 2` (topic-length field) `+ len(topic)` `+ 0/2` (packet_id when QoS 1) `+ len(payload)`.  At a glance:

| Use case | Wire size | Tier |
|---|---|---|
| Plain sensor reading — `home/livingroom/temp` `21.3` | ~30 B | steady |
| Small JSON sensor — `home/livingroom/sensor` `{"t":21.3,"h":45}` | ~45 B | steady |
| Device-prefixed status — `livingRoom/mainLightSwitch/online` `false` | ~45 B | steady |
| Multi-field JSON — `home/livingroom/env` `{"temp":21.3,"hum":45,"pressure":1013,"co2":412}` | ~75 B | steady |
| Verbose JSON sensor (~150 B payload, 20 B topic) | ~175 B | steady |
| HomeAssistant discovery (`homeassistant/.../config` + ~300 B JSON) | ~350 B | **intact** |
| AWS IoT Core shadow `update/accepted` (~250–600 B JSON) | ~300–700 B | **intact** |

So **plain sensor data, small-to-medium JSON readings (payload ≤ ~200 B on a ≤ 40 B topic), and chumicro-`root_topic`-prefixed status messages all parse inline with zero per-message allocation.**  Structured-config workloads — HomeAssistant discovery descriptors, AWS IoT shadow documents, MQTT-SN gateway state — drop into the intact tier: one one-shot buffer per message, freed on the next tick, no churn.  If your typical PUBLISH is consistently above ~250 B, bump `rx_buffer_size` to `512` to keep tier 1 active; if you publish OTA-firmware-class payloads (multi-KB), raise `max_message_bytes` to cover the largest you expect.

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
| [`examples/bench.py`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/mqtt/examples/bench.py) | Self-driving validation bench — deploy + watch serial.  Runs 8 scenarios (tier-1 steady, tier-2 intact, tier-3 oversize, oversize-topic, QoS-1 round-trip, sustained burst, keepalive) against a real broker and prints a pass/fail summary with per-scenario heap deltas + tick latency.  Companion [`examples/bench_host.py`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/mqtt/examples/bench_host.py) captures the verdict from the broker and can publish a 64 KB hostile payload for extra tier-3 stress (host-side, needs `pip install paho-mqtt`). |

---

<div class="chumicro-footer" markdown>

[← Home](index.md)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/mqtt) · \
[PyPI](https://pypi.org/project/chumicro-mqtt/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
