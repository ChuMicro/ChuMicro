# chumicro-mqtt

<img src="https://raw.githubusercontent.com/ChuMicro/ChuMicro/main/support/docs/chumicro_tip.png"
align="left" width="64" style="margin-right: 16px; margin-bottom: 8px;">

**A non-blocking MQTT 3.1.1 client (QoS 0 + 1) that fits inside your runner tick.**  MQTT is the lightweight publish/subscribe protocol most IoT brokers speak.

Publish and subscribe at QoS 0 or QoS 1, set a last will, retain messages, and match wildcard topics.  Messages published before the broker connection is up wait in a bounded queue and go out on connect, and inbound size limits keep one huge payload from exhausting a small heap.  No threads, no async: the client does a bounded slice of work per tick, so a slow broker or a large message never stalls the rest of your loop.  Built on [`chumicro-sockets`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/sockets) (TCP + TLS) and [`chumicro-timing`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/timing) (ticks).

<br clear="left">

> Part of the [ChuMicro](https://github.com/ChuMicro/ChuMicro) family: small, focused Python libraries for microcontrollers and laptops. [Browse all libraries.](https://github.com/ChuMicro/ChuMicro/tree/main/libraries)

## Install

```bash
# CircuitPython (after `circup bundle-add ChuMicro/ChuMicro-Bundle`)
circup install chumicro_mqtt

# MicroPython
mpremote mip install github:ChuMicro/ChuMicro-Bundle/chumicro_mqtt

# CPython
pip install chumicro-mqtt
```

For bundle setup, pre-compiled `.mpy` bundles, the experimental channel, and details on PyPI naming, see the [ChuMicro install guide](https://chumicro.com/ChuMicro/guides/install/).

## Quick example

```python
from chumicro_timing import ticks_ms
from chumicro_mqtt import MQTTClient
from chumicro_wifi import WifiConfig, WifiService

wifi = WifiService(WifiConfig(ssid="home-wifi", password="s3cret"))

# On CircuitPython pass radio=wifi.adapter.radio (the WifiService's board
# radio); the kwarg is ignored on MP / CPython.  from_config builds the
# transport factory: the client dials the broker non-blocking (one connect
# phase per tick) and self-heals after drops.
client = MQTTClient.from_config(
    {"mqtt.broker.host": "broker.example.com", "mqtt.broker.port": 1883},
    radio=wifi.adapter.radio,
)

client.on_message = lambda topic, payload: print(topic, payload)
client.connect()

# Drive from a tick loop.
while True:
    now = ticks_ms()
    if client.check(now):
        client.handle(now)
```

In a program with more going on, hand the loop to [`chumicro-runner`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/runner):

```python
from chumicro_runner import Runner

runner = Runner()
runner.add(client)

while True:
    now = runner.tick()
    runner.wait(now)
```

`wait()` parks the CPU until broker traffic arrives or the next keepalive is due.

QoS 0 + QoS 1 are implemented; QoS 2 raises `UnsupportedQoSError`.  Last-will, retained messages, wildcard topic matching (`topic_matches`), and a structured oversized-message policy are all built in.

## What's included

| Symbol | Purpose |
|---|---|
| `MQTTClient(socket, *, client_id, ...)` | Main client.  Runner-shaped (`check(now_ms)`/`handle(now_ms)`).  Topics go on the wire exactly as written. |
| `client.publish(topic, payload, *, qos=0, retain=False, on_publish=None)` | QoS 0 or 1.  Before CONNECTED, the `when_disconnected` policy applies (queue / raise). |
| `client.subscribe(topic, qos=0, *, on_subscribe=None)` | Single-topic subscribe. A declaration valid in any state: call it before `connect()` and the first CONNACK sends it (self-heal reconnects replay it); `on_subscribe` fires once on the granting SUBACK. |
| `client.unsubscribe(topic, *, on_unsubscribe=None)` | Mirror of `subscribe`: retracts the declaration in any state, sends UNSUBSCRIBE when CONNECTED. |
| `client.on_message` + `topic_matches(topic, pattern)` | Inbound routing: the catch-all callback plus the public wildcard matcher (`+` one segment, `#` trailing tail). |
| `client.connect() / .disconnect()` | Lifecycle. |
| `MQTTClient(..., when_disconnected="queue", pre_connect_queue_size=8)` | Pre-connect publish policy (`"queue"` / `"raise"`) and the queue bound. |
| `WhenOversized.{DROP_SILENT,DROP_WITH_EVENT,DISCONNECT}` | Policy for inbound PUBLISHes larger than `rx_buffer_size`. |
| `ProtocolState.{DISCONNECTED,AWAITING_TRANSPORT,CONNECTING,CONNECTED,FAILED}` | Lifecycle states.  `AWAITING_TRANSPORT` appears while a `transport_factory` drives the transport up. |
| `MQTTBackpressureError` | Raised when an outbound publish overflows `max_tx_queue_size` (or the pre-connect queue under `"queue"`).  Drain via `handle()` and retry. |
| `MQTTError` / `MQTTConnectError` / `MQTTProtocolError` / `UnsupportedQoSError` | Exceptions. |
| `topic_matches(topic, pattern)` | Public wildcard matcher.  Encoder + decoder primitives (`encode_publish`, `encode_varlen`, `decode_varlen`) stay internal to `chumicro_mqtt._wire`. |

### Tuning for tick-latency vs throughput

`handle()` does one `recv_into` and one packet `send` per tick (plus, on ticks that dispatched inbound QoS-1 publishes, a single coalesced PUBACK batch), so each call yields back to the runner after a bounded slice of socket work.  Three `MQTTClient(...)` constructor knobs let you trade tick fairness for throughput:

| Knob | Default | What it bounds |
|---|---|---|
| `recv_budget_per_tick` | `1024` (bytes) | Cap on the single per-tick `recv_into` call.  It binds only when `rx_buffer_size` exceeds it (each recv is already limited to the RX buffer's free space); with a large RX buffer it keeps a multi-KB inbound PUBLISH arriving across several ticks instead of one long syscall. |
| `max_tx_queue_size` | `20` packets | Hard cap on pending outbound packets.  Sized for the runner-shaped sensor profile (publish every N seconds; queue stays near zero).  Appending past the cap raises `MQTTBackpressureError`; protocol-internal traffic (PUBACK responses, retransmits, PINGREQ) bypasses the cap so QoS-1 / keepalive contracts hold.  Failed QoS-1 publishes roll back the `packet_id` allocation cleanly so the id pool isn't leaked on backpressure.  Raise for bursty publishers; each slot pins ~8 bytes long-lived on MP / CP. |
| `send_timeout_seconds` | inherits `ack_timeout_seconds` (5 s) | Maximum time the socket can stay non-writable with a packet queued before the client transitions to `FAILED`.  Re-arms on every successful send: a steady drip of small sends never trips it, only a stalled socket does.  Catches NAT-style silent-drops on the outbound path that would otherwise let the queue grow until `MQTTBackpressureError`. |

## Where this fits

Depends on [`chumicro-sockets`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/sockets) (TCP + TLS) and [`chumicro-timing`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/timing) for ticks.  Used directly in app code; no other ChuMicro library depends on it.

## Platform support

Works on CPython, MicroPython, and CircuitPython.

## Examples

| Example | What it shows |
|---|---|
| [`telemetry.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/mqtt/examples/telemetry.py) | Periodic QoS-1 publish on a real CP/MP board.  Brings wifi up, connects to a broker, subscribes to a command topic, publishes a synthetic reading every N seconds while an LED-blink counter verifies the publish never blocks waiting for PUBACK.  Reads wifi and broker config from `runtime_config.msgpack` (chumicro-workspace) with a constants fallback.  Broker host and port must be set explicitly; the library refuses to silently dial a third-party broker.  Cross-runtime (CP + MP). |
| [`bench.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/mqtt/examples/bench.py) | Self-driving validation bench.  Deploy it and watch serial: the device runs the scenarios end-to-end (steady inline, oversized drain, oversize-topic, QoS-1 round-trip, sustained burst, keepalive) against a real broker and prints a pass/fail summary table.  Used to confirm the library's heap-bounded oversize handling and the two-tier inbound model behave as advertised on a 256 KB-RAM-class board.  Optional companion [`bench_host.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/mqtt/examples/bench_host.py) (host-side, needs `pip install paho-mqtt`) captures the verdict from the broker and can publish a 64 KB hostile payload for extra oversized-tier stress. |

## Wiring wifi and broker config for the examples

The hardware-facing examples need wifi credentials and a broker host and port.  The `telemetry` example reads `[wifi]` for credentials and `[telemetry]` for the broker host, port, and topic, from a `runtime_config.msgpack` (chumicro-workspace) with a constants fallback in the file.  The library itself never reads TOML.  It takes a `chumicro-sockets` socket and goes, so config wiring stays in the application layer.

## Memory and leak testing

A host-side suite uses `tracemalloc` to verify the client doesn't leak across its hot paths: QoS 0 and QoS 1 publish, inbound recv, and subscribe/unsubscribe cycles.

## Contributing

Issues, bug reports, and pull requests are welcome, and so is "I ran it on this board and here's what happened", some of the most useful feedback a hardware project can get.  Development happens in the [ChuMicro repository](https://github.com/ChuMicro/ChuMicro), whose contributing guide covers setup and the test workflow.

## Docs

📖 **[Stable docs](https://chumicro.com/ChuMicro/mqtt/stable/)** · **[Experimental docs](https://chumicro.com/ChuMicro/mqtt/experimental/)**

## Find this library

- **PyPI:** [chumicro-mqtt](https://pypi.org/project/chumicro-mqtt/)
- **Bundle:** [ChuMicro-Bundle](https://github.com/ChuMicro/ChuMicro-Bundle/tree/main/chumicro_mqtt) (CircuitPython & MicroPython)
- **Experimental bundle:** [ChuMicro-Bundle-Experimental](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental/tree/main/chumicro_mqtt)
- **Source:** [libraries/mqtt](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/mqtt)

## License

[MIT](https://github.com/ChuMicro/ChuMicro/blob/main/LICENSE)
