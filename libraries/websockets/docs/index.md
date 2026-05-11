# chumicro-websockets

**Non-blocking WebSocket (RFC 6455) client and server for CircuitPython, MicroPython, and CPython.**

An LED keeps blinking through the handshake, frame I/O, and the close handshake — both sides take small turns on every runner tick instead of holding the loop.

## Quick example

```python
from chumicro_websockets import WebSocketClient, WebSocketState
from chumicro_websockets.sockets_factory import chumicro_sockets_factory
from chumicro_timing import ticks_ms
from chumicro_wifi import wifi

client = WebSocketClient(
    connection_factory=chumicro_sockets_factory(radio=wifi.adapter.radio),
)
client.on_text = lambda text: print(text)
client.connect("ws://api.example.com/stream")

while client.state != WebSocketState.CLOSED:
    now = ticks_ms()
    if client.check(now):
        client.handle(now)
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
