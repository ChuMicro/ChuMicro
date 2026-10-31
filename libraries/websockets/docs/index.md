---
title: "chumicro-websockets: WebSocket client and server for CircuitPython and MicroPython"
---

# chumicro-websockets

**Non-blocking WebSocket (RFC 6455) client and server for CircuitPython, MicroPython, and CPython.**

A WebSocket is a network connection that stays open, so a board and a laptop, browser, or server can each send messages whenever they like.  `WebSocketClient` connects your board to a server, and `WebSocketServer` lets other devices connect to your board.  Both do their network work in small steps, so an LED or a button check in the same program keeps running while messages come and go.

## Install

```bash
# CircuitPython (after `circup bundle-add ChuMicro/ChuMicro-Bundle`)
circup install chumicro_websockets

# MicroPython
mpremote mip install github:ChuMicro/ChuMicro-Bundle/chumicro_websockets

# CPython
pip install chumicro-websockets
```

The quick example below also uses `chumicro_runner` and `chumicro_wifi`; install them the same way.

No board running yet?  [Start here](https://chumicro.com/ChuMicro/guides/start-here/) goes from a new board to your own code running on it.  [Installing libraries](https://chumicro.com/ChuMicro/guides/install/) covers registering the bundle, the experimental channel, and the pre-compiled `.mpy` packages.

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

# radio= is the CircuitPython radio; MicroPython and CPython ignore it.
client = WebSocketClient(transport_factory=connector_factory(radio=wifi.adapter.radio))
client.on_text = lambda text: print("received:", text)
client.connect("ws://192.168.1.42:8765/")
runner.add(client)


def send_hello(now_ms):
    if client.state == WebSocketState.OPEN:
        client.send_text("hello")


runner.add_periodic(send_hello, period_ms=5000)

while True:
    now_ms = runner.tick()  # wifi, the client, and the timer each take a turn
    runner.wait(now_ms)     # then the CPU idles until a message arrives or the timer is due
```

A `Runner` keeps a list of tasks.  `runner.tick()` gives each one a short turn, and `runner.wait()` then idles the CPU until a message arrives or the timer is due.  The [User Guide](guide.md) covers the server side, reconnecting after a drop, and reading messages with a generator.  Each [example](guide.md#examples) has a one-line command to run the other end on your laptop.

## Documentation

- [User Guide](guide.md): clients, servers, reconnecting, generators, callbacks, errors, bring-your-own transport, memory notes, and per-tick knobs
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
