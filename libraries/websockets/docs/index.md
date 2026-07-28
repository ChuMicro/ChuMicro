# chumicro-websockets

**Non-blocking WebSocket (RFC 6455) client and server for CircuitPython, MicroPython, and CPython.**

An LED keeps blinking through the handshake, frame I/O, and the close handshake. Both sides take small turns on every runner tick instead of holding the loop.

## Quick example

```python
from chumicro_websockets import WebSocketClient, WebSocketState
from chumicro_sockets.sockets_factory import connector_factory
from chumicro_timing import ticks_ms
from chumicro_wifi import WifiConfig, WifiService

wifi = WifiService(WifiConfig(ssid="home-wifi", password="s3cret"))

client = WebSocketClient(
    transport_factory=connector_factory(radio=wifi.adapter.radio),
)
client.on_text = lambda text: print(text)
client.connect("ws://api.example.com/stream")

while client.state != WebSocketState.CLOSED:
    now = ticks_ms()
    if client.check(now):
        client.handle(now)
```

`wifi.adapter.radio` is the board radio on CircuitPython and `None` on MicroPython and CPython, where the connector needs no radio.  Bringing your own socket instead of `chumicro-sockets` works too: `transport_factory` takes any `(host, port, use_tls)` callable.

## Documentation

- [User Guide](guide.md): generator flows, client and server services, callbacks, bring-your-own transport, memory notes, and per-tick knobs
- [API Reference](api.md): `WebSocketClient`, `WebSocketServer`, and the close codes and errors they raise
- [Testing Helpers](testing.md): using `FakeConnection` and `FakeListener` in your tests

---

<div class="chumicro-footer" markdown>

[← All ChuMicro Libraries](../../)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/websockets) · \
[PyPI](https://pypi.org/project/chumicro-websockets/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
