# chumicro-mqtt

<img src="https://raw.githubusercontent.com/ChuMicro/ChuMicro/main/support/docs/chumicro_tip.png"
align="left" width="64" style="margin-right: 16px; margin-bottom: 8px;">

Non-blocking MQTT 3.1.1 client (QoS 0 + 1) for CircuitPython, MicroPython, and CPython.  Built on `chumicro-sockets` (TCP + TLS) and `chumicro-timing` (ticks).  Runner-shaped: `check(now_ms) -> bool` + `handle(now_ms)` from your tick loop — no threads, no async.

<br clear="left">

> Part of the [ChuMicro](https://github.com/ChuMicro/ChuMicro) family — small, focused Python libraries for microcontrollers and laptops. [See all libraries.](https://github.com/ChuMicro/ChuMicro#whats-in-the-box)

## Installation

### CircuitPython ([circup](https://github.com/adafruit/circup))

circup is CircuitPython's package manager — it uses [bundles](https://learn.adafruit.com/keep-your-circuitpython-libraries-on-devices-up-to-date-with-circup/bundle-commands) to find third-party packages. Register the ChuMicro bundle once, then install by name:

```bash
circup bundle-add ChuMicro/ChuMicro-Bundle
circup install chumicro-mqtt
```

### MicroPython ([mip](https://docs.micropython.org/en/latest/reference/packages.html))

```bash
mpremote mip install github:ChuMicro/ChuMicro-Bundle/chumicro_mqtt
```

> **Want pre-compiled `.mpy` bytecode?** Add `mpy6/` before the package name for faster startup and lower RAM usage on boards with mpy format v6 (MicroPython 1.24+):
> ```
> mpremote mip install github:ChuMicro/ChuMicro-Bundle/mpy6/chumicro_mqtt
> ```

### CPython (pip)

```bash
pip install chumicro-mqtt
```

*Just getting started? Skip this — the install commands above are all you need.*

<details>
<summary>Experimental (pre-release) versions and channel switching</summary>

Pre-release builds are published automatically when a library version is bumped. Do not register both bundles simultaneously — circup may pick either version for a given package.

```bash
# CircuitPython — switch to experimental
circup bundle-remove ChuMicro/ChuMicro-Bundle              # skip if never added
circup bundle-add ChuMicro/ChuMicro-Bundle-Experimental
circup install chumicro-mqtt

# MicroPython
mpremote mip install github:ChuMicro/ChuMicro-Bundle-Experimental/chumicro_mqtt

# CPython
pip install chumicro-mqtt-experimental
```

</details>

## Quick example

```python
from chumicro_sockets import tcp_client_socket
from chumicro_timing import ticks_ms
from chumicro_mqtt import MQTTClient

# CP needs `radio=wifi.radio`; MP / CPython ignore the kwarg.
sock = tcp_client_socket("broker.example.com", 1883, radio=None)
sock.setblocking(False)
client = MQTTClient(sock, client_id="my-thing", keep_alive_seconds=60)

client.on_message = lambda topic, payload: print(topic, payload)
client.connect()

# Drive from your tick loop — no threads, no async.
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
| `ProtocolState.{DISCONNECTED,CONNECTING,CONNECTED,DISCONNECTING,FAILED}` | Lifecycle states. |
| `MQTTError` / `MQTTConnectError` / `MQTTProtocolError` / `UnsupportedQoSError` | Exceptions. |
| Encoder + decoder primitives (`encode_publish`, `encode_varlen`, `decode_varlen`, `encode_string`, `topic_matches`) | Public for downstream tooling. |

## Platform support

Works on CPython, MicroPython, and CircuitPython.

> **Heads-up for small-RAM CircuitPython boards (e.g. Pi Pico W).**
> `chumicro-mqtt` plus its `chumicro-sockets` + `chumicro-wifi` deps
> exceed CircuitPython's heap budget for inline-bootstrap (RAM-mode)
> deploys on the smallest supported boards — the parser needs ~14 KB
> of heap on top of each chunk's own size to AST-build, which a 264 KB-
> SRAM rp2 port doesn't have to spare.  Symptom: `MemoryError: memory
> allocation failed, allocating <N> bytes` partway through the deploy.
> Use **flash mode** on those boards — `mpy-cross` compiles the
> payload off-device, sidestepping the on-device parse pressure
> entirely.  From `chumicro-deploy` directly: `--deploy-mode flash`.
> From a `chumicro-workspace` project: set `deploy_mode: flash` on
> the device entry in `devices.yml`.  The recovery layer in
> `chumicro-deploy` recognises the symptom and points at the same
> fix when it surfaces — but pre-empting it via `devices.yml` saves a
> failed-deploy round-trip.

## Examples

| Example | What it shows |
|---|---|
| [`quickstart.py`](examples/quickstart.py) | FakeSocket-driven CONNECT → SUBSCRIBE → PUBLISH → inbound-message round trip.  Identical on every runtime; no network needed. |
| [`circuitpython_telemetry.py`](examples/circuitpython_telemetry.py) | Periodic QoS-1 publish on a real CP/MP board.  Brings wifi up, connects to a broker, subscribes to a command topic, publishes a synthetic reading every N seconds while an LED-blink counter verifies the publish never blocks waiting for PUBACK.  Reads wifi + broker config from `runtime_config.msgpack` (chumicro-workspace) with constants fallback.  Default broker: `test.mosquitto.org:1883`. |

## Configuring wifi + broker for examples and functional tests

Real-network functional tests in `functional_tests/test_real_*.py` and the hardware-prefixed examples in `examples/circuitpython_*.py` need wifi credentials (and optionally a broker override).  How you supply them depends on whether you're inside the chumicro mono-repo or using this library in your own project.

### Inside the chumicro mono-repo

`python scripts/run.py setup` generates `chumicro-dev-config.toml` at the repo root (gitignored).  Uncomment and fill in:

```toml
[wifi]
ssid = "your-wifi-ssid"
password = "your-wifi-password"

# Optional — defaults to test.mosquitto.org:1883 when omitted.
[mqtt.broker]
host = "test.mosquitto.org"
port = 1883
```

The library's `functional_tests/conftest.py` reads this file and materialises a `_test_creds.py` shim alongside the test.  Without it, the real-network tests skip silently.

### Using `chumicro-mqtt` outside the mono-repo

Two paths, depending on whether you're using a `chumicro-workspace`:

* **With a workspace (recommended).**  Put wifi + broker config in your workspace's `secrets.yml` and per-thing `config.toml`, run `chumicro-workspace deploy --thing <name>`, and the example reads them via `chumicro_config.load_runtime_config()`.  The telemetry example reads `[wifi]` for credentials and `[telemetry]` for the broker host/port/topic — see the example file for keys.
* **Raw single-file deploy** (no workspace).  Edit the `WIFI_SSID` / `WIFI_PASSWORD` / `BROKER_HOST` / `BROKER_PORT` / `TOPIC` constants near the top of the example file before copying it to `/code.py` (CP) or `/main.py` (MP).  The constants are the fallback when no `runtime_config.msgpack` is present.

The library itself never reads either source — it takes a `chumicro-sockets` socket and goes.  The config wiring is application-layer.

## Memory + leak testing

The host-side suite under `tests/test_memory_pressure.py` uses `tracemalloc` to verify the client doesn't leak across hot paths (QoS 0 / QoS 1 publish, inbound recv, subscribe/unsubscribe cycles).

For real-board fragmentation testing, `.scratch/run_mqtt_perf.py` deploys a long-running publish/subscribe loop that samples `gc.mem_free()` periodically.  Verified live: 5-minute soak on Pi Pico W MP at 1 Hz publish, 299 publishes + 299 received, **0 bytes net heap drift**.  All four supported boards (Lolin S2 CP/MP, Pi Pico W CP/MP) pass the 30 s drift check.

## Developing this library

Host-side tests live in `tests/`; real-board functional tests belong in `functional_tests/`.

```bash
python scripts/run.py test --libraries mqtt
python scripts/run.py test-libraries-functional --library mqtt
```

Before running device tests, generate local board config files with `python scripts/run.py setup`, then fill in `devices.yml`. See the [contributing guide](https://github.com/ChuMicro/ChuMicro/blob/main/CONTRIBUTING.md) and the [device testing guide](https://github.com/ChuMicro/ChuMicro/blob/main/docs/contributing/device-testing.md) for the full workflow.

## Docs

📖 **[Stable docs](https://chumicro.github.io/ChuMicro/mqtt/stable/)** · **[Experimental docs](https://chumicro.github.io/ChuMicro/mqtt/experimental/)**

## Find this library

- **PyPI:** [chumicro-mqtt](https://pypi.org/project/chumicro-mqtt/)
- **Bundle:** [ChuMicro-Bundle](https://github.com/ChuMicro/ChuMicro-Bundle/tree/main/chumicro_mqtt) (CircuitPython & MicroPython)
- **Experimental bundle:** [ChuMicro-Bundle-Experimental](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental/tree/main/chumicro_mqtt)
- **Source:** [libraries/mqtt](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/mqtt)
