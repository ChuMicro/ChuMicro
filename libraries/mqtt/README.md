# chumicro-mqtt

<img src="https://raw.githubusercontent.com/ChuMicro/ChuMicro/main/support/docs/chumicro_tip.png"
align="left" width="64" style="margin-right: 16px; margin-bottom: 8px;">

**Send sensor readings and receive commands over MQTT from a CircuitPython or MicroPython board, while the rest of your program keeps running.**

MQTT is the publish/subscribe protocol most home-automation and IoT services speak.  Your board connects to a *broker* (Mosquitto on a laptop, Home Assistant, or a cloud service), publishes messages to named *topics* such as `home/kitchen/temperature`, and subscribes to the topics it wants to hear.

Your program never waits on the network.  Each `mqtt.handle()` call does one small step of work and returns, so an LED keeps blinking and a button keeps answering while a message is on its way.  If the broker or the wifi drops, the client reconnects on its own and sends the messages it held in the meantime.  Built on [`chumicro-sockets`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/sockets) (TCP + TLS) and [`chumicro-timing`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/timing) (millisecond ticks).

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

Publish a reading every five seconds and print every message sent to `demo/cmd`.  This is CircuitPython, which joins your wifi from `settings.toml` at startup:

```python
import wifi

from chumicro_mqtt import MQTTClient
from chumicro_timing import Rate, ticks_ms

mqtt = MQTTClient.from_config(
    {"mqtt.broker.host": "192.168.1.20", "mqtt.broker.port": 1883},  # your broker's address
    radio=wifi.radio,
)
mqtt.on_message = lambda topic, payload: print(topic, payload)
mqtt.subscribe("demo/cmd")
mqtt.connect()

publish_timer = Rate(5000, ticks_ms())  # due once every 5000 ms

while True:
    now_ms = ticks_ms()
    if mqtt.check(now_ms):
        mqtt.handle(now_ms)  # one small step: connect, send, receive, or reconnect
    if publish_timer.due(now_ms):
        mqtt.publish("demo/temperature", "21.5")
```

On MicroPython, connect with `network.WLAN` first, then drop `import wifi` and the `radio=` line.

You can call `publish()` and `subscribe()` before the broker has answered: the client holds them and sends them once it connects, and repeats the subscription after every reconnect.  [`telemetry.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/mqtt/examples/telemetry.py) is the full program, with wifi setup, a broker on your laptop, and output that shows a reconnect.

In a program with more going on, [`chumicro-runner`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/runner) turns the loop for you and lets the CPU rest between events:

```python
from chumicro_runner import Runner

runner = Runner()
runner.add(mqtt)
runner.add_periodic(lambda now_ms: mqtt.publish("demo/temperature", "21.5"), period_ms=5000)

while True:
    now_ms = runner.tick()   # the client and the timer each take one small step
    runner.wait(now_ms)      # then the CPU rests until broker traffic or the next timer
```

## What it does

- **QoS 0 and QoS 1.**  QoS ("quality of service") 0 sends a message once with no confirmation.  QoS 1 waits for the broker to confirm and sends again until it does.  QoS 2 raises `UnsupportedQoSError`.
- **Retained messages.**  `publish(..., retain=True)` asks the broker to keep the last message on a topic and hand it to anyone who subscribes later.
- **Last will.**  `set_will(topic, message)` leaves a message with the broker to publish for you if the board drops off without disconnecting.
- **Wildcard subscriptions.**  `+` matches one level of a topic (`home/+/temperature`) and `#` matches everything below (`home/#`).  `topic_matches()` applies the same rules inside your own code.
- **Reconnects on its own.**  After a dropped connection the client dials again, at once and then backing off to once a minute, and sends what it held.
- **Bounded memory.**  An incoming message larger than the receive buffer (256 bytes by default) is skipped without allocating room for it, so one huge payload cannot run a small board out of RAM.

## What's included

| Symbol | Purpose |
|---|---|
| `MQTTClient.from_config(config, *, radio=None, ssl_context=None, ...)` | Builds a client from `mqtt.broker.host` / `mqtt.broker.port` (plus optional `mqtt.client_id`, `mqtt.username`, `mqtt.password`).  The client dials the broker itself and dials again after a drop.  Pass `radio=wifi.radio` on CircuitPython and `ssl_context=` for TLS. |
| `MQTTClient(socket, *, client_id, ...)` | The client, built from a socket or a `transport_factory` you supply.  `check(now_ms)` says whether it has work to do and `handle(now_ms)` does one small step of it. |
| `mqtt.publish(topic, payload, *, qos=0, retain=False, on_publish=None)` | Sends `payload` (`bytes` or `str`) to `topic`.  Before the broker has answered, the message waits in a queue of eight and goes out on connect.  `on_publish(topic, payload)` runs once the message is sent (QoS 0) or the broker confirms it (QoS 1). |
| `mqtt.subscribe(topic, qos=0, *, on_subscribe=None)` | Asks for messages on `topic`.  Call it any time, before `connect()` included: the client sends it once connected and again after every reconnect. |
| `mqtt.unsubscribe(topic, *, on_unsubscribe=None)` | Stops the messages `subscribe()` asked for. |
| `mqtt.on_message`, `on_connect`, `on_disconnect` | Callbacks you assign: `on_message(topic, payload)` for each arriving message, `on_connect()` each time the broker accepts the board, `on_disconnect()` when a working connection drops. |
| `mqtt.next_message()` | The other way to receive: a generator task (a function with `yield`, run by `chumicro-runner`) loops on `message = yield from mqtt.next_message()`. |
| `mqtt.connect()` / `mqtt.disconnect()` / `mqtt.hold()` | Start connecting, hang up cleanly, or pause automatic reconnects until the next `connect()`. |
| `mqtt.set_will(topic, message, *, qos=0, retain=False)` | The last will the broker publishes if the board vanishes. |
| `mqtt.state` / `mqtt.last_error` | Where the connection stands (a `ProtocolState` value) and the most recent failure. |
| `topic_matches(topic, pattern)` | `True` when `topic` matches a wildcard `pattern`. |
| `default_client_id(prefix="chumicro")` | A per-board client id built from the chip's unique id. |
| `WhenOversized.{DROP_SILENT,DROP_WITH_EVENT,DISCONNECT}` | What happens to an incoming message larger than `rx_buffer_size`. |
| `MQTTError` / `MQTTConnectError` / `MQTTProtocolError` / `MQTTBackpressureError` / `UnsupportedQoSError` | Exceptions.  `MQTTBackpressureError` means a send queue is full: let `handle()` drain it and try again. |

The [user guide](https://chumicro.com/ChuMicro/mqtt/stable/guide/) covers TLS, receive-buffer sizing, and the knobs that trade loop responsiveness for throughput.

## Where this fits

Depends on [`chumicro-sockets`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/sockets) (TCP + TLS) and [`chumicro-timing`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/timing) for ticks.  Used directly in app code; no other ChuMicro library depends on it.

## Platform support

Works on CPython, MicroPython, and CircuitPython.

## Examples

| Example | What it shows |
|---|---|
| [`telemetry.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/mqtt/examples/telemetry.py) | Start here.  Publishes a reading every five seconds at QoS 1, prints each broker confirmation, and prints any command sent to `chumicro-demo/cmd`.  Stop the broker and it holds readings, then reconnects and sends them.  CircuitPython and MicroPython. |
| [`receive_stream.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/mqtt/examples/receive_stream.py) | Receives with a plain loop instead of a callback: a generator waits on `mqtt.next_message()`, prints the message, and waits again, while `chumicro-runner` keeps the connection going.  CircuitPython and MicroPython. |
| [`bench.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/mqtt/examples/bench.py) | A one-shot test run against a real broker: small and oversized incoming messages, a QoS 1 round trip, a burst, and keepalive, then a pass/fail table.  The optional laptop-side [`bench_host.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/mqtt/examples/bench_host.py) (needs `pip install paho-mqtt`) collects the verdict and can send a 64 KB message to test the oversized path. |

### Running the examples

The examples need a broker the board can reach.  Mosquitto on your laptop is the quickest: install it (`brew install mosquitto`, or `sudo apt install mosquitto mosquitto-clients`), save these two lines as `mosquitto.conf`, and start it with `mosquitto -c mosquitto.conf -v`:

```text
listener 1883
allow_anonymous true
```

Started without a config file, Mosquitto only accepts connections from the laptop itself.  `mosquitto_sub -h localhost -t 'chumicro-demo/#' -v` in a second terminal shows what the board publishes.

Each example has `WIFI_SSID`, `WIFI_PASSWORD`, and `BROKER_HOST` constants at the top; set `BROKER_HOST` to your laptop's IP address.  In the [ChuMicro repository](https://github.com/ChuMicro/ChuMicro), `chumicro-workspace deploy-example mqtt telemetry` copies an example and the libraries it needs to a board, and takes the wifi and broker settings from `[wifi]` and `[mqtt.broker]` in `secrets.toml` instead.

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
