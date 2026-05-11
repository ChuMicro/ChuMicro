# chumicro-websockets

<img src="https://raw.githubusercontent.com/ChuMicro/ChuMicro/main/support/docs/chumicro_tip.png"
align="left" width="64" style="margin-right: 16px; margin-bottom: 8px;">

**Non-blocking WebSocket (RFC 6455) client and server, plain and TLS.**

RFC 6455 framing and masking, opening + closing handshakes, text + binary + ping/pong, and oversized-message guards.  Plays alongside [`chumicro-http-server`](../http_server/) for combined HTTP + WS / HTTPS + WSS deployments.  Built on [`chumicro-sockets`](../sockets/) and [`chumicro-timing`](../timing/).

<br clear="left">

> Part of the [ChuMicro](https://github.com/ChuMicro/ChuMicro) family — small, focused Python libraries for microcontrollers and laptops. [Browse all libraries.](https://github.com/ChuMicro/ChuMicro/tree/main/libraries)

## Install

```bash
# CircuitPython (after `circup bundle-add ChuMicro/ChuMicro-Bundle`)
circup install chumicro-websockets

# MicroPython
mpremote mip install github:ChuMicro/ChuMicro-Bundle/chumicro_websockets

# CPython
pip install chumicro-websockets
```

For bundle setup, pre-compiled `.mpy` bundles, the experimental channel, and details on PyPI naming, see the [chumicro INSTALL guide](https://github.com/ChuMicro/ChuMicro/blob/main/INSTALL.md).

## Quick example

```python
from chumicro_websockets import WebSocketClient, WebSocketState
from chumicro_websockets.sockets_factory import chumicro_sockets_factory
from chumicro_timing import ticks_ms

client = WebSocketClient(connection_factory=chumicro_sockets_factory())
client.on_text = lambda text: print(f"got: {text}")
client.connect("ws://api.example.com/stream")

while client.state != WebSocketState.CLOSED:
    if client.check(ticks_ms()):
        client.handle(ticks_ms())
```

Framing primitives (`FrameParser`, `encode_frame`, the handshake parsers, the `DEFAULT_*` knob constants) live in `chumicro_websockets._wire` for advanced users + tests; the public top-level surface stays small to keep flash + RAM lean on the device.

## What's included

| Component | Purpose |
|---|---|
| `parse_ws_url(url)` | Split `ws://` / `wss://` URLs into `(scheme, host, port, path)`. |
| `make_websocket_key()` / `derive_accept_key(key)` | RFC 6455 §4.2.2 nonce + accept-token derivation. |
| `encode_client_handshake(...)` / `encode_server_handshake_response(...)` | Build the HTTP/1.1 opening-handshake bytes. |
| `HandshakeResponseParser` / `HandshakeRequestParser` | Streaming validators for the opening handshake from each side. |
| `FrameParser` | Streaming RFC 6455 §5 binary-frame parser; one frame at a time. |
| `encode_frame(opcode, payload, *, fin, mask)` | Build one outbound frame; clients pass `mask=`, servers don't. |
| `encode_close_payload(code, reason)` / `parse_close_payload(body)` | CLOSE-frame body codec. |
| `validate_text_payload(bytes)` | RFC 6455 §8.1 UTF-8 validation for text frames. |
| `WebSocketState` | Lifecycle constants (`CONNECTING` / `OPEN` / `CLOSING` / `CLOSED`). |
| `WebSocketError` + subclasses | Exception hierarchy: protocol, handshake, URL, timeout, backpressure, oversized, state. |

## Where this fits

Depends on [`chumicro-sockets`](../sockets/) and [`chumicro-timing`](../timing/).  Pairs with [`chumicro-http-server`](../http_server/) for combined HTTP + WS / HTTPS + WSS deployments.

## Platform support

Works on CPython, MicroPython, and CircuitPython.

## Examples

| Example | What it shows |
|---|---|
| [`client.py`](examples/client.py) | WebSocket client on real CP/MP hardware — brings wifi up via the bundled `helpers`, connects to a configured echo server, prints every inbound message while a counter ticks alongside. |
| [`server.py`](examples/server.py) | WebSocket echo server on real CP/MP hardware — accepts inbound connections on the configured host/port and echoes every frame back. |

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
