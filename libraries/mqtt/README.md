# chumicro-mqtt

<img src="https://raw.githubusercontent.com/ChuMicro/ChuMicro/main/support/docs/chumicro_tip.png"
align="left" width="64" style="margin-right: 16px; margin-bottom: 8px;">

**A non-blocking MQTT 3.1.1 client (QoS 0 + 1) that fits inside your runner tick.**

QoS 0 + QoS 1, last-will, retain, pattern-routed handlers, and a structured oversized-message policy — runner-shaped, no threads, no async.  A configurable per-tick recv budget keeps a 100 KB inbound blob from monopolising the loop, and failed QoS-1 publishes roll back the packet-id allocation cleanly on backpressure.  Built on [`chumicro-sockets`](../sockets/) (TCP + TLS) and [`chumicro-timing`](../timing/) (ticks).

<br clear="left">

> Part of the [ChuMicro](https://github.com/ChuMicro/ChuMicro) family — small, focused Python libraries for microcontrollers and laptops. [Browse all libraries.](https://github.com/ChuMicro/ChuMicro/tree/main/libraries)

## Install

```bash
# CircuitPython (after `circup bundle-add ChuMicro/ChuMicro-Bundle`)
circup install chumicro-mqtt

# MicroPython
mpremote mip install github:ChuMicro/ChuMicro-Bundle/chumicro_mqtt

# CPython
pip install chumicro-mqtt
```

For bundle setup, pre-compiled `.mpy` bundles, the experimental channel, and details on PyPI naming, see the [chumicro INSTALL guide](https://github.com/ChuMicro/ChuMicro/blob/main/INSTALL.md).

## Quick example

```python
from chumicro_sockets import tcp_client_socket
from chumicro_timing import ticks_ms
from chumicro_mqtt import MQTTClient

# CP auto-detects `wifi.radio`; MP / CPython have no radio.
sock = tcp_client_socket("broker.example.com", 1883)
sock.setblocking(False)
client = MQTTClient(sock, client_id="my-thing", keep_alive_seconds=60)

client.on_message = lambda topic, payload: print(topic, payload)
client.connect()

# Drive from a tick loop.
while True:
    now = ticks_ms()
    if client.check(now):
        client.handle(now)
```

QoS 0 + QoS 1 are implemented; QoS 2 raises `UnsupportedQoSError`.  Last-will, retained messages, pattern-routed handlers, and a structured oversized-message policy are all built in.

## What's included

| Symbol | Purpose |
|---|---|
| `MQTTClient(socket, *, client_id, ...)` | Main client.  Runner-shaped (`check(now_ms)`/`handle(now_ms)`). |
| `client.publish(topic, payload, *, qos=0, retain=False, on_publish=None)` | QoS 0 or 1. |
| `client.subscribe(topic, qos=0, *, on_subscribe=None)` | Single-topic subscribe. |
| `client.unsubscribe(topic, *, on_unsubscribe=None)` | |
| `client.add_pattern_handler(pattern, handler)` | Route inbound messages by topic pattern. |
| `client.connect() / .disconnect()` | Lifecycle. |
| `WhenOversized.{DROP_SILENT,DROP_WITH_EVENT,DISCONNECT}` | Policy for inbound payloads above `max_message_size`. |
| `ProtocolState.{DISCONNECTED,CONNECTING,CONNECTED,FAILED}` | Lifecycle states. |
| `MQTTBackpressureError` | Raised when an outbound publish/subscribe overflows `max_tx_queue_size` — caller's signal to drain via `handle()` and retry. |
| `MQTTError` / `MQTTConnectError` / `MQTTProtocolError` / `UnsupportedQoSError` | Exceptions. |
| Encoder + decoder primitives (`encode_publish`, `encode_varlen`, `decode_varlen`, `encode_string`, `topic_matches`) | Public for downstream tooling. |

### Tuning for tick-latency vs throughput

Two `MQTTClient(...)` constructor knobs let you trade tick fairness for throughput:

| Knob | Default | What it bounds |
|---|---|---|
| `recv_budget_per_tick` | `1024` (bytes) | Soft cap on bytes drained from the socket in one `handle()` call.  Without this, a 100 KB blob in a fat kernel TCP buffer (lwIP on rp2 holds 16–32 KB) would monopolize the tick until drained — visibly stuttering a concurrent LED blink or sub-second control loop.  Raise for fast big-blob ingestion at the cost of LED smoothness. |
| `max_tx_queue_size` | `20` packets | Hard cap on pending outbound packets.  Sized for the runner-shaped sensor profile (publish every N seconds; queue stays near zero).  Appending past the cap raises `MQTTBackpressureError`; protocol-internal traffic (PUBACK responses, retransmits, PINGREQ) bypasses the cap so QoS-1 / keepalive contracts hold.  Failed QoS-1 publishes roll back the `packet_id` allocation cleanly so the id pool isn't leaked on backpressure.  Raise for bursty publishers; each slot pins ~8 bytes long-lived on MP / CP. |

A naive `recv_into` loop without `recv_budget_per_tick` can starve cooperative tasks when the kernel TCP buffer is full.

## Where this fits

Depends on [`chumicro-sockets`](../sockets/) (TCP + TLS) and [`chumicro-timing`](../timing/) for ticks.  Used directly in app code; no other ChuMicro library depends on it.

## Platform support

Works on CPython, MicroPython, and CircuitPython.

## Examples

| Example | What it shows |
|---|---|
| [`telemetry.py`](examples/telemetry.py) | Periodic QoS-1 publish on a real CP/MP board.  Brings wifi up, connects to a broker, subscribes to a command topic, publishes a synthetic reading every N seconds while an LED-blink counter verifies the publish never blocks waiting for PUBACK.  Reads wifi + broker config from `runtime_config.msgpack` (chumicro-workspace) with constants fallback.  Broker host/port must be set explicitly — the library refuses to silently dial a third-party broker.  Cross-runtime (CP + MP). |

## Wiring wifi + broker config for examples and functional tests

The hardware-prefixed examples + real-network suites in `functional_tests/test_real_*.py` need wifi credentials and a broker host / port.  See [`docs/wiring-wifi-credentials.md`](https://github.com/ChuMicro/ChuMicro/blob/main/docs/wiring-wifi-credentials.md) for the workspace-based and raw single-file paths — the `telemetry` example reads `[wifi]` for credentials and `[telemetry]` for the broker host / port / topic.  The library itself never reads TOML — it takes a `chumicro-sockets` socket and goes; config wiring is application-layer.

## Memory + leak testing

The host-side suite under `tests/test_memory_pressure_pytest.py` uses `tracemalloc` to verify the client doesn't leak across hot paths (QoS 0 / QoS 1 publish, inbound recv, subscribe/unsubscribe cycles).

For real-board fragmentation testing, `.scratch/run_mqtt_perf.py` deploys a long-running publish/subscribe loop that samples `gc.mem_free()` periodically.  Verified live: 5-minute soak on Pi Pico W MP at 1 Hz publish, 299 publishes + 299 received, **0 bytes net heap drift**.  All four supported boards (Lolin S2 CP/MP, Pi Pico W CP/MP) pass the 30 s drift check.

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
