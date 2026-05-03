# chumicro-websockets

Non-blocking WebSocket (RFC 6455) client + server for CircuitPython, MicroPython, and CPython.  Built on `chumicro-sockets` and `chumicro-timing` so an LED can keep blinking through the handshake, frame I/O, and the close handshake.

## Quick example

```python
from chumicro_websockets import WebSocketClient, WebSocketState
from chumicro_websockets.sockets_factory import chumicro_sockets_factory
from chumicro_wifi import wifi

client = WebSocketClient(
    connection_factory=chumicro_sockets_factory(radio=wifi.adapter.radio),
)
client.on_text = lambda text: print(text)
client.connect("ws://api.example.com/stream")

while client.state != WebSocketState.CLOSED:
    if client.check(now_ms()):
        client.handle(now_ms())
```

## Documentation

- [User Guide](guide.md) — getting started and usage patterns
- [API Reference](api.md) — full API documentation
- [Testing Helpers](testing.md) — fakes for downstream test suites

---

<div class="chumicro-footer" markdown>

[← All ChuMicro Libraries](../../)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/websockets) · \
[PyPI](https://pypi.org/project/chumicro-websockets/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
