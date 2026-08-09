# chumicro-mqtt

**Non-blocking MQTT 3.1.1 client (QoS 0 + 1) for CircuitPython, MicroPython, and CPython.**

Built on `chumicro-sockets` for TCP and TLS and `chumicro-timing` for ticks.  Every step of the protocol takes one tick of work, so your LED keeps blinking through CONNECT, SUBSCRIBE, PUBLISH, and PUBACK round-trips.

## Quick example

```python
from chumicro_timing import ticks_ms
from chumicro_mqtt import MQTTClient

# from_config builds the transport factory: the client dials the broker
# without blocking (one connect phase per tick) and self-heals after a
# drop.  On CircuitPython add radio=wifi.adapter.radio from your
# chumicro-wifi WifiService; MicroPython and CPython need no radio.
client = MQTTClient.from_config(
    {"mqtt.broker.host": "broker.example.com", "mqtt.broker.port": 1883},
)

client.on_message = lambda topic, payload: print(topic, payload)
client.connect()

# Drive it from your tick loop, or hand it to a runner.
while True:
    now = ticks_ms()
    if client.check(now):
        client.handle(now)
```

## Documentation

- [User Guide](guide.md): connecting, publishing at QoS 0 and QoS 1, subscribing and pattern routing, last-will, TLS, wifi-drop self-heal, and the tuning knobs
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
