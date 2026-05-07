# User Guide

## Overview

`chumicro-mqtt` is a non-blocking MQTT 3.1.1 client (QoS 0 + 1) for CircuitPython, MicroPython, and CPython.  Built on `chumicro-sockets` (TCP + TLS) and `chumicro-timing` (ticks); no `async`, no threads, no blocking on network I/O.  The tick-based runner pattern (`check(now_ms)` / `handle(now_ms)`) drives every protocol step:

* `client.check(now_ms) -> bool` — does the client have work to do this tick?
* `client.handle(now_ms)` — do one tick of work (one recv, one parse, one queued send, one deadline check).

That means an LED can keep blinking on the same board while a publish or subscribe is in flight, and a sensor read can happen between MQTT ticks.

QoS 0 + QoS 1 are implemented; QoS 2 raises `UnsupportedQoSError`.  Last-will, retained messages, pattern-routed handlers, and a structured oversized-message policy are all built in.

## Getting started

```python
from chumicro_sockets import tcp_client_socket
from chumicro_timing import ticks_ms
from chumicro_mqtt import MQTTClient

# CP needs `radio=wifi.radio`; MP / CPython ignore the kwarg.
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

`MQTTClient` actually enforces non-blocking mode on every socket it acquires (force-`setblocking(False)`), so the explicit `sock.setblocking(False)` line above is belt-and-suspenders.  Don't omit it — MP plain TCP defaults to blocking, and a blocking `recv` on a Pi Pico W RP2 silently stalls the tick loop for 5–30 s.

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
* The TLS handshake is synchronous inside `wrap_socket(...)` — budget for ~100–500 ms of listener stall during connection setup.
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

## Tuning for tick-latency vs throughput

Two constructor knobs let you trade tick fairness for throughput:

| Knob | Default | What it bounds |
|---|---|---|
| `recv_budget_per_tick` | `1024` (bytes) | Soft cap on bytes drained from the socket in one `handle()` call.  Without this, a 100 KB blob in a fat kernel TCP buffer (lwIP on rp2 holds 16–32 KB) would monopolize the tick until drained — visibly stuttering a concurrent LED blink or sub-second control loop.  Raise for fast big-blob ingestion at the cost of LED smoothness. |
| `max_tx_queue_size` | `100` packets | Hard cap on pending outbound packets.  Appending past the cap raises `MQTTBackpressureError`; protocol-internal traffic (PUBACK responses, retransmits, PINGREQ) bypasses the cap so QoS-1 / keepalive contracts hold.  Failed QoS-1 publishes roll back the `packet_id` allocation cleanly so the id pool isn't leaked on backpressure.  Raise for bursty publishers; lower for memory-tight boards. |

```python
client = MQTTClient(
    sock,
    client_id="my-thing",
    recv_budget_per_tick=4096,             # faster big-blob ingestion
    max_tx_queue_size=20,                  # tighter on a 256 KB-RAM board
)
```

The `recv_budget_per_tick` knob exists because of a real production bug: a naive "drain until EAGAIN" loop on a fat kernel buffer can iterate 60–128 times before draining, blowing tick latency past 25 ms on a Pi Pico W RP2.

## Oversized-message policy

`max_message_size` caps a single inbound PUBLISH payload (default 256 KB).  When a payload exceeds the cap, `when_oversized` selects the policy:

```python
from chumicro_mqtt import MQTTClient, WhenOversized

client = MQTTClient(
    sock,
    client_id="my-thing",
    max_message_size=8192,                          # 8 KB cap
    when_oversized=WhenOversized.DROP_WITH_EVENT,   # default
)
```

Three policies:

| `WhenOversized` | Behavior |
|---|---|
| `DROP_SILENT` | Skip the message, no event. |
| `DROP_WITH_EVENT` (default) | Skip the message, fire `on_oversized(topic, byte_count)` for telemetry. |
| `DISCONNECT` | Cleanly disconnect from the broker — appropriate when oversized inputs indicate a misconfiguration. |

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

Five states: `DISCONNECTED`, `CONNECTING`, `CONNECTED`, `DISCONNECTING`, `FAILED`.  `client.connected` is a shortcut for `state == CONNECTED`.

## Examples

| Example | What it shows |
|---|---|
| [`examples/quickstart.py`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/mqtt/examples/quickstart.py) | `FakeSocket`-driven CONNECT → SUBSCRIBE → PUBLISH → inbound-message round trip.  Identical on every runtime; no network needed. |
| [`examples/circuitpython_telemetry.py`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/mqtt/examples/circuitpython_telemetry.py) | Periodic QoS-1 publish on a real CP/MP board.  Brings wifi up, connects to a broker, subscribes to a command topic, publishes a synthetic reading every N seconds while an LED-blink counter verifies the publish never blocks waiting for PUBACK. |

## What's new

- **0.1.5**: Documentation buildout — guide rewrite, knob explainers.
- **0.1.4**: Production-readiness sweep — `recv_budget_per_tick`, `max_tx_queue_size`, `MQTTBackpressureError`, `WhenOversized` policy enum.
- **0.1.3**: Per-`packet_id` `InFlightTable` for QoS 1 retries; explicit `ProtocolState` ladder; 8→4 source-file consolidation.
- **0.1.0**: Initial library — Decision 0029 Phase 6 scope.

---

<div class="chumicro-footer" markdown>

[← Home](index.md)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/mqtt) · \
[PyPI](https://pypi.org/project/chumicro-mqtt/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
