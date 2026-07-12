# chumicro-mqtt

<img src="https://raw.githubusercontent.com/ChuMicro/ChuMicro/main/support/docs/chumicro_tip.png"
align="left" width="64" style="margin-right: 16px; margin-bottom: 8px;">

**A non-blocking MQTT 3.1.1 client (QoS 0 + 1) that fits inside your runner tick.**

QoS 0 + QoS 1, last-will, retain, wildcard topic matching, automatic per-device topic prefixing, a bounded pre-connect publish queue, and a two-tier inbound size model that keeps heap usage bounded on memory-tight boards — runner-shaped, no threads, no async.  A configurable per-tick recv budget keeps a large inbound blob from monopolising the loop, and failed QoS-1 publishes roll back the packet-id allocation cleanly on backpressure.  Built on [`chumicro-sockets`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/sockets) (TCP + TLS) and [`chumicro-timing`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/timing) (ticks).

<br clear="left">

> Part of the [ChuMicro](https://github.com/ChuMicro/ChuMicro) family — small, focused Python libraries for microcontrollers and laptops. [Browse all libraries.](https://github.com/ChuMicro/ChuMicro/tree/main/libraries)

## Install

```bash
# CircuitPython (after `circup bundle-add ChuMicro/ChuMicro-Bundle`)
circup install chumicro_mqtt

# MicroPython
mpremote mip install github:ChuMicro/ChuMicro-Bundle/chumicro_mqtt

# CPython
pip install chumicro-mqtt
```

For bundle setup, pre-compiled `.mpy` bundles, the experimental channel, and details on PyPI naming, see the [chumicro INSTALL guide](https://github.com/ChuMicro/ChuMicro/blob/main/INSTALL.md).

## Quick example

```python
from chumicro_timing import ticks_ms
from chumicro_mqtt import MQTTClient

# On CircuitPython pass radio=wifi.radio; the kwarg is ignored on MP / CPython.
# from_config builds the transport factory: the client dials the broker
# non-blocking (one connect phase per tick) and self-heals after drops.
client = MQTTClient.from_config(
    {"mqtt.broker.host": "broker.example.com", "mqtt.broker.port": 1883},
    radio=wifi.radio,
)

client.on_message = lambda topic, payload: print(topic, payload)
client.connect()

# Drive from a tick loop.
while True:
    now = ticks_ms()
    if client.check(now):
        client.handle(now)
```

QoS 0 + QoS 1 are implemented; QoS 2 raises `UnsupportedQoSError`.  Last-will, retained messages, wildcard topic matching (`topic_matches`), and a structured oversized-message policy are all built in.

## What's included

| Symbol | Purpose |
|---|---|
| `MQTTClient(socket, *, client_id, ...)` | Main client.  Runner-shaped (`check(now_ms)`/`handle(now_ms)`).  Topics go on the wire exactly as written. |
| `client.publish(topic, payload, *, qos=0, retain=False, on_publish=None)` | QoS 0 or 1.  Before CONNECTED, the `when_disconnected` policy applies (queue / raise). |
| `client.subscribe(topic, qos=0, *, on_subscribe=None)` | Single-topic subscribe. A declaration valid in any state — call it before `connect()` and the first CONNACK sends it (self-heal reconnects replay it); `on_subscribe` fires once on the granting SUBACK. |
| `client.unsubscribe(topic, *, on_unsubscribe=None)` | Mirror of `subscribe`: retracts the declaration in any state, sends UNSUBSCRIBE when CONNECTED. |
| `client.on_message` + `topic_matches(topic, pattern)` | Inbound routing: the catch-all callback plus the public wildcard matcher (`+` one segment, `#` trailing tail). |
| `client.connect() / .disconnect()` | Lifecycle. |
| `MQTTClient(..., when_disconnected="queue", pre_connect_queue_size=8)` | Pre-connect publish policy (`"queue"` / `"raise"`) and the queue bound. |
| `WhenOversized.{DROP_SILENT,DROP_WITH_EVENT,DISCONNECT}` | Policy for inbound PUBLISHes larger than `rx_buffer_size`. |
| `ProtocolState.{DISCONNECTED,AWAITING_TRANSPORT,CONNECTING,CONNECTED,FAILED}` | Lifecycle states.  `AWAITING_TRANSPORT` appears while a `transport_factory` drives the transport up. |
| `MQTTBackpressureError` | Raised when an outbound publish overflows `max_tx_queue_size` (or the pre-connect queue under `"queue"`) — caller's signal to drain via `handle()` and retry. |
| `MQTTError` / `MQTTConnectError` / `MQTTProtocolError` / `UnsupportedQoSError` | Exceptions. |
| `topic_matches(topic, pattern)` | Public wildcard matcher.  Encoder + decoder primitives (`encode_publish`, `encode_varlen`, `decode_varlen`, `encode_string`) stay internal to `chumicro_mqtt._wire`. |

### Tuning for tick-latency vs throughput

`handle()` does exactly one `recv_into` and one `send` per tick, so each call yields back to the runner after one socket syscall.  Three `MQTTClient(...)` constructor knobs let you trade tick fairness for throughput:

| Knob | Default | What it bounds |
|---|---|---|
| `recv_budget_per_tick` | `1024` (bytes) | Cap on the single per-tick `recv_into` call.  Without it, an oversized-tier rolling drain of a multi-KB inbound PUBLISH would draw the whole payload in one syscall; the cap means it arrives across several ticks instead, keeping each tick short.  Raise for fast big-blob ingestion at the cost of per-syscall latency. |
| `max_tx_queue_size` | `20` packets | Hard cap on pending outbound packets.  Sized for the runner-shaped sensor profile (publish every N seconds; queue stays near zero).  Appending past the cap raises `MQTTBackpressureError`; protocol-internal traffic (PUBACK responses, retransmits, PINGREQ) bypasses the cap so QoS-1 / keepalive contracts hold.  Failed QoS-1 publishes roll back the `packet_id` allocation cleanly so the id pool isn't leaked on backpressure.  Raise for bursty publishers; each slot pins ~8 bytes long-lived on MP / CP. |
| `send_timeout_seconds` | inherits `ack_timeout_seconds` (5 s) | Maximum time the socket can stay non-writable with a packet queued before the client transitions to `FAILED`.  Re-arms on every successful send -- a steady drip of small sends never trips it, only a stalled socket does.  Catches NAT-style silent-drops on the outbound path that would otherwise let the queue grow until `MQTTBackpressureError`. |

## Where this fits

Depends on [`chumicro-sockets`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/sockets) (TCP + TLS) and [`chumicro-timing`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/timing) for ticks.  Used directly in app code; no other ChuMicro library depends on it.

## Platform support

Works on CPython, MicroPython, and CircuitPython.

## Examples

| Example | What it shows |
|---|---|
| [`telemetry.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/mqtt/examples/telemetry.py) | Periodic QoS-1 publish on a real CP/MP board.  Brings wifi up, connects to a broker, subscribes to a command topic, publishes a synthetic reading every N seconds while an LED-blink counter verifies the publish never blocks waiting for PUBACK.  Reads wifi + broker config from `runtime_config.msgpack` (chumicro-workspace) with constants fallback.  Broker host/port must be set explicitly — the library refuses to silently dial a third-party broker.  Cross-runtime (CP + MP). |
| [`bench.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/mqtt/examples/bench.py) | Self-driving validation bench.  Deploy + watch serial — the device runs the scenarios end-to-end (steady inline, oversized drain, oversize-topic, QoS-1 round-trip, sustained burst, keepalive) against a real broker and prints a pass/fail summary table.  Used to confirm the library's heap-bounded oversize handling and the two-tier inbound model behave as advertised on a 256 KB-RAM-class board.  Optional companion [`bench_host.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/mqtt/examples/bench_host.py) (host-side, needs `pip install paho-mqtt`) captures the verdict from the broker and can publish a 64 KB hostile payload for extra oversized-tier stress. |

## Wiring wifi + broker config for examples and functional tests

The hardware-prefixed examples + real-network suites in `functional_tests/test_real_*.py` need wifi credentials and a broker host / port.  See [`docs/wiring-wifi-credentials.md`](https://github.com/ChuMicro/ChuMicro/blob/main/docs/wiring-wifi-credentials.md) for the workspace-based and raw single-file paths — the `telemetry` example reads `[wifi]` for credentials and `[telemetry]` for the broker host / port / topic.  The library itself never reads TOML — it takes a `chumicro-sockets` socket and goes; config wiring is application-layer.

## Memory + leak testing

The host-side suite under `tests/test_memory_pressure_pytest.py` uses `tracemalloc` to verify the client doesn't leak across hot paths (QoS 0 / QoS 1 publish, inbound recv, subscribe/unsubscribe cycles).

## Contributing

Working on `chumicro-mqtt` itself?  Clone the [mono-repo](https://github.com/ChuMicro/ChuMicro) if you haven't already — the rest of the workflow assumes you're inside that workspace.

```bash
pip install -e .[test]
pytest tests/                  # host-side tests
pytest functional_tests/       # on-device tests (needs a board registered in devices.yml)
```

Register a board before running functional tests: `chumicro-workspace add-device <id> --address <port>`.

## Docs

📖 **[Stable docs](https://chumicro.github.io/ChuMicro/mqtt/stable/)** · **[Experimental docs](https://chumicro.github.io/ChuMicro/mqtt/experimental/)**

## Find this library

- **PyPI:** [chumicro-mqtt](https://pypi.org/project/chumicro-mqtt/)
- **Bundle:** [ChuMicro-Bundle](https://github.com/ChuMicro/ChuMicro-Bundle/tree/main/chumicro_mqtt) (CircuitPython & MicroPython)
- **Experimental bundle:** [ChuMicro-Bundle-Experimental](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental/tree/main/chumicro_mqtt)
- **Source:** [libraries/mqtt](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/mqtt)

## License

[MIT](https://github.com/ChuMicro/ChuMicro/blob/main/LICENSE)
