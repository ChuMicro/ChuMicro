---
title: "chumicro-mqtt: non-blocking MQTT client for CircuitPython and MicroPython"
---

# chumicro-mqtt

**Send sensor readings and receive commands over MQTT from a CircuitPython or MicroPython board, while the rest of your program keeps running.**

MQTT is the publish/subscribe protocol most home-automation and IoT services speak.  Your board connects to a *broker* (Mosquitto on a laptop, Home Assistant, or a cloud service), publishes messages to named *topics* such as `home/kitchen/temperature`, and subscribes to the topics it wants to hear.

Your program never waits on the network.  Each `mqtt.handle()` call does one small step of work and returns, so an LED keeps blinking and a button keeps answering while a message is on its way.  If the broker or the wifi drops, the client reconnects on its own and sends the messages it held in the meantime.  The same code runs on CircuitPython, MicroPython, and CPython.

## Install

```bash
# CircuitPython (after `circup bundle-add ChuMicro/ChuMicro-Bundle`)
circup install chumicro_mqtt

# MicroPython
mpremote mip install github:ChuMicro/ChuMicro-Bundle/chumicro_mqtt

# CPython
pip install chumicro-mqtt
```

The `Runner` loop in the quick example comes from `chumicro-runner`.  Install it the same way.

[Start here](https://chumicro.com/ChuMicro/guides/start-here/) takes a new board from flashing CircuitPython or MicroPython to running your own blink.  [Installing libraries](https://chumicro.com/ChuMicro/guides/install/) covers registering the bundle, the pre-compiled `.mpy` packages, the experimental channel, and why package names use a hyphen on PyPI and an underscore on the board.

## Quick example

This CircuitPython `code.py` publishes a reading every five seconds and prints every message sent to `demo/cmd`.  It relies on CircuitPython's own wifi join, which runs at startup when `settings.toml` sets `CIRCUITPY_WIFI_SSID` and `CIRCUITPY_WIFI_PASSWORD`:

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

On MicroPython, join wifi with `network.WLAN` first, drop `import wifi`, and drop the `radio=` line.

`mqtt` is a service, an object a loop drives through two methods.  `check(now_ms)` returns `True` when the client has work to do.  `handle(now_ms)` does one small step of that work.  `publish()` and `subscribe()` work before the broker has answered.  The client holds them, sends them once it connects, and repeats the subscription after every reconnect.  [`telemetry.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/mqtt/examples/telemetry.py) is the full program, with wifi setup, a broker on your laptop, and output that shows a reconnect.

In a program with more going on, hand the loop to [`chumicro-runner`](https://chumicro.com/ChuMicro/runner/stable/):

```python
from chumicro_runner import Runner

runner = Runner()
runner.add(mqtt)
runner.add_periodic(lambda now_ms: mqtt.publish("demo/temperature", "21.5"), period_ms=5000)

while True:
    now_ms = runner.tick()   # the client and the timer each take one small step
    runner.wait(now_ms)      # sleep until broker traffic arrives or the timer is due
```

## Documentation

- [User Guide](guide.md): connecting, publishing at QoS 0 and QoS 1, subscribing and wildcard routing, last will, TLS, reconnecting after a drop, and the settings that trade loop responsiveness for throughput
- [API Reference](api.md): `MQTTClient`, its protocol states, and the errors it raises
- [Testing Helpers](testing.md): the canned broker packets and `new_client` for your tests

---

<div class="chumicro-footer" markdown>

[← All ChuMicro Libraries](../../)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/mqtt) · \
[PyPI](https://pypi.org/project/chumicro-mqtt/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
