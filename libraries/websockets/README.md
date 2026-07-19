# chumicro-websockets

<img src="https://raw.githubusercontent.com/ChuMicro/ChuMicro/main/support/docs/chumicro_tip.png"
align="left" width="64" style="margin-right: 16px; margin-bottom: 8px;">

**Non-blocking WebSocket (RFC 6455) client and server, plain and TLS.**

RFC 6455 framing and masking, opening + closing handshakes, text + binary + ping/pong, and oversized-message guards.  Plays alongside [`chumicro-http-server`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/http_server) for combined HTTP + WS / HTTPS + WSS deployments.  Built on [`chumicro-sockets`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/sockets) and [`chumicro-timing`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/timing).

<br clear="left">

> Part of the [ChuMicro](https://github.com/ChuMicro/ChuMicro) family — small, focused Python libraries for microcontrollers and laptops. [Browse all libraries.](https://github.com/ChuMicro/ChuMicro/tree/main/libraries)

## Install

```bash
# CircuitPython (after `circup bundle-add ChuMicro/ChuMicro-Bundle`)
circup install chumicro_websockets

# MicroPython
mpremote mip install github:ChuMicro/ChuMicro-Bundle/chumicro_websockets

# CPython
pip install chumicro-websockets
```

For bundle setup, pre-compiled `.mpy` bundles, the experimental channel, and details on PyPI naming, see the [chumicro INSTALL guide](https://github.com/ChuMicro/ChuMicro/blob/main/INSTALL.md).

## Quick example

Client:

```python
from chumicro_websockets import WebSocketClient, WebSocketState
from chumicro_sockets.sockets_factory import connector_factory
from chumicro_timing import ticks_ms

client = WebSocketClient(transport_factory=connector_factory())
client.on_text = lambda text: print(f"got: {text}")
client.connect("ws://api.example.com/stream")

while client.state != WebSocketState.CLOSED:
    if client.check(ticks_ms()):
        client.handle(ticks_ms())
```

Server:

```python
from chumicro_websockets import WebSocketServer
from chumicro_sockets import listener
from chumicro_timing import ticks_ms

def on_connection(connection):
    connection.on_text = lambda text: connection.send_text(f"echo: {text}")

server = WebSocketServer(
    listener=listener("0.0.0.0", 8765),
    on_connection=on_connection,
)

while True:
    if server.check(ticks_ms()):
        server.handle(ticks_ms())
```

## What's included

| Component | Purpose |
|---|---|
| `WebSocketClient` | Non-blocking RFC 6455 client; runner-shaped `check(now_ms)` / `handle(now_ms)`. |
| `WebSocketServer` + `Connection` | Standalone WebSocket server owning a listening socket; one `Connection` per accepted client. |
| `WhenOversized` | Policy for inbound messages above `max_message_bytes`: `DROP_SILENT`, `DROP_WITH_EVENT`, `DISCONNECT`. |
| `WebSocketState` | Lifecycle constants (`CONNECTING` / `OPEN` / `CLOSING` / `CLOSED`). |
| `parse_ws_url(url)` | Split `ws://` / `wss://` URLs into `(scheme, host, port, path)`. |
| `make_websocket_key()` / `derive_accept_key(key)` | RFC 6455 §4.2.2 nonce + accept-token derivation. |
| `WebSocketError` + subclasses | Exception hierarchy: protocol, handshake, URL, timeout, backpressure, state. |
| `OPCODE_*` / `CLOSE_*` constants | RFC 6455 opcode and close-code values. |

Wire-format primitives (`FrameParser`, `encode_frame`, the handshake parsers and encoders, the close-payload codec, `validate_text_payload`, the `DEFAULT_*` knob constants) live in `chumicro_websockets._wire` for advanced users and tests; the public top-level surface stays small to keep flash + RAM lean on the device.

## Where this fits

Depends on [`chumicro-sockets`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/sockets) and [`chumicro-timing`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/timing).  Pairs with [`chumicro-http-server`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/http_server) for combined HTTP + WS / HTTPS + WSS deployments.

## Platform support

Works on CPython, MicroPython, and CircuitPython.

## Examples

| Example | What it shows |
|---|---|
| [`client.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/websockets/examples/client.py) | WebSocket client on real CP/MP hardware — brings wifi up via the bundled `helpers`, connects to a configured echo server, prints every inbound message while a counter ticks alongside. |
| [`server.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/websockets/examples/server.py) | WebSocket echo server on real CP/MP hardware — accepts inbound connections on the configured host/port and echoes every frame back. |

## Contributing

Working on `chumicro-websockets` itself?  Clone the [mono-repo](https://github.com/ChuMicro/ChuMicro) if you haven't already — the rest of the workflow assumes you're inside that workspace.

```bash
pip install -e .[test]
pytest tests/                  # host-side tests
pytest functional_tests/       # on-device tests (needs a board registered in devices.yml)
```

Register a board before running functional tests: `chumicro-workspace add-device <id> --address <port>`.

## Docs

📖 **[Stable docs](https://chumicro.github.io/ChuMicro/websockets/stable/)** · **[Experimental docs](https://chumicro.github.io/ChuMicro/websockets/experimental/)**

## Find this library

- **PyPI:** [chumicro-websockets](https://pypi.org/project/chumicro-websockets/)
- **Bundle:** [ChuMicro-Bundle](https://github.com/ChuMicro/ChuMicro-Bundle/tree/main/chumicro_websockets) (CircuitPython & MicroPython)
- **Experimental bundle:** [ChuMicro-Bundle-Experimental](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental/tree/main/chumicro_websockets)
- **Source:** [libraries/websockets](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/websockets)

## License

[MIT](https://github.com/ChuMicro/ChuMicro/blob/main/LICENSE)
