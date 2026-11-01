# chumicro-websockets

<img src="https://raw.githubusercontent.com/ChuMicro/ChuMicro/main/support/docs/chumicro_tip.png"
align="left" width="64" style="margin-right: 16px; margin-bottom: 8px;">

**Non-blocking WebSocket (RFC 6455) client and server, plain and TLS.**

A WebSocket is a network connection that stays open, so a board and a laptop, browser, or server can each send messages whenever they like.  A board can push sensor readings to a dashboard or take commands from a script without polling for them.  `WebSocketClient` connects your board to a server, and `WebSocketServer` lets other devices connect to your board.  Both do their network work in small steps, so an LED or a button check in the same program keeps running while messages come and go.  Text and binary messages, ping/pong keep-alives, `wss://` over TLS, and a size cap on incoming messages are all built in.  The same code runs on CircuitPython, MicroPython, and CPython.

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

This server sends every text message back to the client that sent it:

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
    runner.wait(now_ms)     # sleep until a client needs attention
```

To talk to it from a laptop, run `pip install websockets`, then `python -m websockets ws://<board-ip>:8765/`, and type a line.

## What's included

| Symbol | Description |
|---|---|
| `WebSocketClient` | Connects to a `ws://` or `wss://` server.  Add it to a `Runner`, or call its `check(now_ms)` and `handle(now_ms)` from your own loop |
| `WebSocketServer` and `Connection` | Listens for clients on a port.  Hands you one `Connection` per client, with the client's send methods and every client callback except `on_open` |
| `InboundMessage` | What `next_message()` returns when a generator task reads messages: `is_text`, `text`, `data` |
| `WhenOversized` | What to do with an incoming message larger than `max_message_bytes`: `DROP_SILENT`, `DROP_WITH_EVENT`, `DISCONNECT` |
| `WebSocketState` | Connection states: `CONNECTING`, `OPEN`, `CLOSING`, `CLOSED` |
| `parse_ws_url(url)` | Split a `ws://` or `wss://` URL into `(scheme, host, port, path)` |
| `make_websocket_key()` / `derive_accept_key(key)` | The handshake key and the accept token from RFC 6455 §4.2.2 |
| `WebSocketError` and subclasses | Errors for the protocol, the handshake, the URL, a timeout, backpressure, and a call in the wrong state |
| `OPCODE_*` / `CLOSE_*` constants | RFC 6455 opcode and close-code values |

The wire-format pieces (`FrameParser`, `encode_frame`, the handshake parsers and encoders, the close-payload codec, `validate_text_payload`, and the `DEFAULT_*` setting values) live in `chumicro_websockets._wire`, for tests and custom tools.

## Where this fits

Depends on [`chumicro-sockets`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/sockets) for the network connections and [`chumicro-timing`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/timing) for the millisecond clock.  Both install with this library.  Runs as a service on a [`chumicro-runner`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/runner) loop, as the quick example shows.  It runs beside [`chumicro-http-server`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/http_server) in the same program, so one board can serve a web page on one port and a WebSocket on another.

## Platform support

Works on CPython, MicroPython, and CircuitPython.

## Examples

| Example | What it shows |
|---|---|
| [`client.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/websockets/examples/client.py) | Sends `hello N` to an echo server every five seconds, prints each reply, and reconnects after the connection drops |
| [`server.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/websockets/examples/server.py) | Echoes every text message back to its sender and sends a count to every connected client every five seconds |
| [`receive_stream.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/websockets/examples/receive_stream.py) | Prints each message a server streams, read with a `next_message()` generator task, and reconnects when the stream ends |

### Running the examples

Each example runs on CircuitPython and MicroPython boards, and its docstring says what to run on a laptop for the other end.  Each one joins wifi through `helpers.py`, which sits beside it in `examples/`.  Set `WIFI_SSID` and `WIFI_PASSWORD` at the top of the example.  Copy the example to the board as `code.py` on CircuitPython or `main.py` on MicroPython, together with `helpers.py` and the libraries it imports.  From a clone of the [ChuMicro repository](https://github.com/ChuMicro/ChuMicro), `chumicro-workspace deploy-example websockets client` does the copying and takes the wifi settings from `secrets.toml`.  [Wiring wifi credentials](https://chumicro.com/ChuMicro/guides/wiring-wifi-credentials/) walks through both ways.

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
