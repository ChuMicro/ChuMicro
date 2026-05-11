# chumicro-mqtt

**Non-blocking MQTT 3.1.1 client (QoS 0 + 1) for CircuitPython, MicroPython, and CPython.**

Built on `chumicro-sockets` and `chumicro-timing` — your LED keeps blinking through CONNECT, SUBSCRIBE, PUBLISH, and PUBACK round-trips because every step takes one tick of work.

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

# Drive from your tick loop — runner-shaped.
while True:
    now = ticks_ms()
    if client.check(now):
        client.handle(now)
```

## Documentation

- [User Guide](guide.md) — connecting, QoS 1, last-will, TLS, pattern routing, tuning knobs
- [API Reference](api.md) — full API documentation
- [Testing Helpers](testing.md) — fakes for downstream test suites

---

<div class="chumicro-footer" markdown>

[← All ChuMicro Libraries](../../)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/mqtt) · \
[PyPI](https://pypi.org/project/chumicro-mqtt/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
