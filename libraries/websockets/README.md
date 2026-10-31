# chumicro-websockets

<img src="https://raw.githubusercontent.com/ChuMicro/ChuMicro/main/support/docs/chumicro_tip.png"
align="left" width="64" style="margin-right: 16px; margin-bottom: 8px;">

**Non-blocking WebSocket (RFC 6455) client and server, plain and TLS.**

A WebSocket is a network connection that stays open, so a board and a laptop, browser, or server can each send messages whenever they like.  A board can push sensor readings to a dashboard or take commands from a script without polling for them.  `WebSocketClient` connects your board to a server, and `WebSocketServer` lets other devices connect to your board.  Both do their network work in small steps, so an LED or a button check in the same program keeps running while messages come and go.  Text and binary messages, ping/pong keep-alives, `wss://` over TLS, and a size cap on incoming messages are all built in.

<br clear="left">

> Part of the [ChuMicro](https://github.com/ChuMicro/ChuMicro) family: small, focused Python libraries for microcontrollers and laptops. [Browse all libraries.](https://github.com/ChuMicro/ChuMicro/tree/main/libraries)

## Install

```bash
# CircuitPython (after `circup bundle-add ChuMicro/ChuMicro-Bundle`)
circup install chumicro_websockets

# MicroPython
mpremote mip install github:ChuMicro/ChuMicro-Bundle/chumicro_websockets

# CPython
pip install chumicro-websockets
```

The quick examples below also use `chumicro_runner` and `chumicro_wifi`; install them the same way.  For bundle setup, pre-compiled `.mpy` bundles, the experimental channel, and details on PyPI naming, see the [ChuMicro install guide](https://chumicro.com/ChuMicro/guides/install/).

## Quick example

A client that joins wifi, connects to a WebSocket server, sends `hello` every five seconds, and prints every message the server sends back:

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

A `Runner` from `chumicro-runner` keeps a list of tasks.  `runner.tick()` gives each one a short turn, and `runner.wait()` then idles the CPU until a message arrives or the timer is due.  The [`client.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/websockets/examples/client.py) example adds reconnecting after a dropped connection.

A server that sends every text message back to the client that sent it:

```python
from chumicro_runner import Runner
from chumicro_sockets.sockets_factory import listener_factory
from chumicro_websockets import WebSocketServer
from chumicro_wifi import WifiConfig, WifiService

runner = Runner()
wifi = WifiService(WifiConfig(ssid="home-wifi", password="s3cret"))
runner.add(wifi)
while not wifi.connected:
    now_ms = runner.tick()
    runner.wait(now_ms)
print(f"connect to ws://{wifi.ip}:8765/")


def on_connection(connection):
    # Runs once for each client that connects: send its text messages back.
    connection.on_text = lambda text: connection.send_text("echo: " + text)


server = WebSocketServer(
    listener_factory=listener_factory("0.0.0.0", 8765, radio=wifi.adapter.radio),
    on_connection=on_connection,
)
runner.add(server)

while True:
    now_ms = runner.tick()  # the server accepts clients and moves their messages
    runner.wait(now_ms)     # then the CPU idles until a client needs attention
```

To talk to it from a laptop, run `pip install websockets`, then `python -m websockets ws://<board-ip>:8765/`, and type a line.

## What's included

| Component | Purpose |
|---|---|
| `WebSocketClient` | Connects to a `ws://` or `wss://` server.  Add it to a `Runner`, or call its `check(now_ms)` / `handle(now_ms)` pair from your own loop. |
| `WebSocketServer` + `Connection` | Listens for clients on a port; hands you one `Connection` per client, with the client's send methods and every client callback except `on_open`. |
| `InboundMessage` | What `next_message()` returns when you read messages with a generator: `is_text`, `text`, `data`. |
| `WhenOversized` | What to do with an incoming message larger than `max_message_bytes`: `DROP_SILENT`, `DROP_WITH_EVENT`, `DISCONNECT`. |
| `WebSocketState` | Connection states (`CONNECTING` / `OPEN` / `CLOSING` / `CLOSED`). |
| `parse_ws_url(url)` | Split `ws://` / `wss://` URLs into `(scheme, host, port, path)`. |
| `make_websocket_key()` / `derive_accept_key(key)` | RFC 6455 §4.2.2 nonce + accept-token derivation. |
| `WebSocketError` + subclasses | Exception hierarchy: protocol, handshake, URL, timeout, backpressure, state. |
| `OPCODE_*` / `CLOSE_*` constants | RFC 6455 opcode and close-code values. |

The wire-format pieces (`FrameParser`, `encode_frame`, the handshake parsers and encoders, the close-payload codec, `validate_text_payload`, and the `DEFAULT_*` knob values) live in `chumicro_websockets._wire`, for tests and custom tools.

## Where this fits

Depends on [`chumicro-sockets`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/sockets), which opens the network connections, and [`chumicro-timing`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/timing), which supplies the millisecond clock.  Runs beside [`chumicro-http-server`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/http_server) in the same program, so one board can serve a web page on one port and a WebSocket on another, over TLS or not.

## Platform support

Works on CPython, MicroPython, and CircuitPython.

## Examples

| Example | What it shows |
|---|---|
| [`client.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/websockets/examples/client.py) | Sends `hello N` to an echo server every five seconds, prints each reply, and reconnects after the connection drops. |
| [`server.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/websockets/examples/server.py) | Echoes every text message back to its sender and sends a count to every connected client every five seconds. |
| [`receive_stream.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/websockets/examples/receive_stream.py) | Prints each message a server streams, read with a `next_message()` generator, and reconnects when the stream ends. |

Each example runs on CircuitPython and MicroPython boards, ends in a `while True:` loop that runs until you unplug the board, and says in its docstring what to run on a laptop for the other end.

## Contributing

Issues, bug reports, and pull requests are welcome, and so is "I ran it on this board and here's what happened", some of the most useful feedback a hardware project can get.  Development happens in the [ChuMicro repository](https://github.com/ChuMicro/ChuMicro), whose contributing guide covers setup and the test workflow.

## Docs

📖 **[Stable docs](https://chumicro.com/ChuMicro/websockets/stable/)** · **[Experimental docs](https://chumicro.com/ChuMicro/websockets/experimental/)**

## Find this library

- **PyPI:** [chumicro-websockets](https://pypi.org/project/chumicro-websockets/)
- **Bundle:** [ChuMicro-Bundle](https://github.com/ChuMicro/ChuMicro-Bundle/tree/main/chumicro_websockets) (CircuitPython & MicroPython)
- **Experimental bundle:** [ChuMicro-Bundle-Experimental](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental/tree/main/chumicro_websockets)
- **Source:** [libraries/websockets](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/websockets)

## License

[MIT](https://github.com/ChuMicro/ChuMicro/blob/main/LICENSE)
