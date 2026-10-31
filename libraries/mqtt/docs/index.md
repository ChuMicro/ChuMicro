---
title: "chumicro-mqtt: non-blocking MQTT client for CircuitPython and MicroPython"
---

# chumicro-mqtt

**Send sensor readings and receive commands over MQTT from a CircuitPython or MicroPython board, while the rest of your program keeps running.**

MQTT is the publish/subscribe protocol most home-automation and IoT services speak.  Your board connects to a *broker* (Mosquitto on a laptop, Home Assistant, or a cloud service), publishes messages to named *topics*, and subscribes to the topics it wants to hear.

Each `mqtt.handle()` call does one small step of network work and returns, so your LED keeps blinking while a message is on its way.  If the broker or the wifi drops, the client reconnects on its own and sends the messages it held in the meantime.  The same code runs under desktop Python (CPython) for a laptop script or a test.

## Install

```bash
# CircuitPython (after `circup bundle-add ChuMicro/ChuMicro-Bundle`)
circup install chumicro_mqtt

# MicroPython
mpremote mip install github:ChuMicro/ChuMicro-Bundle/chumicro_mqtt

# CPython
pip install chumicro-mqtt
```

No board running yet?  [Start here](https://chumicro.com/ChuMicro/guides/start-here/) goes from a new board to your own code running on it.  [Installing libraries](https://chumicro.com/ChuMicro/guides/install/) covers registering the bundle, the experimental channel, and the pre-compiled `.mpy` packages.

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

On MicroPython, connect with `network.WLAN` first, then drop `import wifi` and the `radio=` line.  The [User Guide](guide.md#getting-started) walks through each line, and `examples/telemetry.py` is the full program, with a broker on your laptop.

## Documentation

- [User Guide](guide.md): connecting, publishing at QoS 0 and QoS 1, subscribing and wildcard routing, last will, TLS, reconnecting after a drop, and the tuning knobs
- [API Reference](api.md): `MQTTClient`, its protocol states, and the error types it raises
- [Testing Helpers](testing.md): using the canned broker packets and `new_client` in your tests

---

<div class="chumicro-footer" markdown>

[← All ChuMicro Libraries](../../)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/mqtt) · \
[PyPI](https://pypi.org/project/chumicro-mqtt/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
