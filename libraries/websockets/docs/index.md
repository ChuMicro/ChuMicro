---
title: "chumicro-websockets: WebSocket client and server for CircuitPython and MicroPython"
---

# chumicro-websockets

**Non-blocking WebSocket (RFC 6455) client and server, plain and TLS.**

A WebSocket is a network connection that stays open, so a board and a laptop, browser, or server can each send messages whenever they like.  A board can push sensor readings to a dashboard or take commands from a script without polling for them.  `WebSocketClient` connects your board to a server, and `WebSocketServer` lets other devices connect to your board.  Both do their network work in small steps, so an LED or a button check in the same program keeps running while messages come and go.  Text and binary messages, ping/pong keep-alives, `wss://` over TLS, and a size cap on incoming messages are all built in.  The same code runs on CircuitPython, MicroPython, and CPython.

## Install

```bash
# CircuitPython (after `circup bundle-add ChuMicro/ChuMicro-Bundle`)
circup install chumicro_websockets

# MicroPython
mpremote mip install github:ChuMicro/ChuMicro-Bundle/chumicro_websockets

# CPython
pip install chumicro-websockets
```

The quick example joins wifi with `chumicro-wifi` and runs on a `Runner` from `chumicro-runner`.  Install both the same way.

[Start here](https://chumicro.com/ChuMicro/guides/start-here/) takes a new board from flashing CircuitPython or MicroPython to running your own blink.  [Installing libraries](https://chumicro.com/ChuMicro/guides/install/) covers registering the bundle, the pre-compiled `.mpy` packages, the experimental channel, and why package names use a hyphen on PyPI and an underscore on the board.

## Quick example

This client joins wifi, connects to a WebSocket server, sends `hello` every five seconds, and prints every message the server sends back:

```python
from chumicro_runner import Runner
from chumicro_sockets.sockets_factory import connector_factory
from chumicro_websockets import WebSocketClient, WebSocketState
from chumicro_wifi import WifiConfig, WifiService

runner = Runner()

# Join wifi first.  WifiService also rejoins on its own after a drop.
wifi = WifiService(WifiConfig(ssid="home-wifi", password="s3cret"))
runner.add(wifi)
while not wifi.connected:
    now_ms = runner.tick()
    runner.wait(now_ms)

# CircuitPython needs radio=, and MicroPython and CPython ignore it.
client = WebSocketClient(transport_factory=connector_factory(radio=wifi.adapter.radio))
client.on_text = lambda text: print("received:", text)
client.connect("ws://192.168.1.42:8765/")
runner.add(client)


def send_hello(now_ms):
    if client.state == WebSocketState.OPEN:
        client.send_text("hello")


runner.add_periodic(send_hello, period_ms=5000)

while True:
    now_ms = runner.tick()  # wifi, the client, and the timer each take one small step
    runner.wait(now_ms)     # sleep until a message arrives or the timer is due
```

`runner.tick()` runs every job that is due.  `runner.wait(now_ms)` sleeps until the next one is.  `client` is a service, an object a loop drives through two methods.  `check(now_ms)` returns `True` when the client has work to do.  `handle(now_ms)` does one small step of that work.  The [`client.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/websockets/examples/client.py) example adds reconnecting after a dropped connection.

## Documentation

- [User Guide](guide.md): clients, servers, reconnecting, reading messages with a generator task, callbacks, errors, bringing your own transport, memory notes, and per-tick settings
- [API Reference](api.md): `WebSocketClient`, `WebSocketServer`, and the close codes and errors they raise
- [Testing Helpers](testing.md): `FakeConnection` and `FakeListener` for your tests

---

<div class="chumicro-footer" markdown>

[← All ChuMicro Libraries](../../)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/websockets) · \
[PyPI](https://pypi.org/project/chumicro-websockets/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
