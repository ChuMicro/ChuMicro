# chumicro-sockets

<img src="https://raw.githubusercontent.com/ChuMicro/ChuMicro/main/support/docs/chumicro_tip.png"
align="left" width="64" style="margin-right: 16px; margin-bottom: 8px;">

**One TCP / TLS / UDP socket surface across CircuitPython, MicroPython, and CPython.**

One entry per socket shape (`connector`, `listener`, `udp_socket`) hides the per-runtime adapter selection; TLS is a `tls=` flag on each.  Custom-CA TLS, server-side certs, and an in-memory `FakeSocket` for downstream library tests are all included.

<br clear="left">

> Part of the [ChuMicro](https://github.com/ChuMicro/ChuMicro) family — small, focused Python libraries for microcontrollers and laptops. [Browse all libraries.](https://github.com/ChuMicro/ChuMicro/tree/main/libraries)

## Install

```bash
# CircuitPython (after `circup bundle-add ChuMicro/ChuMicro-Bundle`)
circup install chumicro_sockets

# MicroPython
mpremote mip install github:ChuMicro/ChuMicro-Bundle/chumicro_sockets

# CPython
pip install chumicro-sockets
```

For bundle setup, pre-compiled `.mpy` bundles, the experimental channel, and details on PyPI naming, see the [chumicro INSTALL guide](https://github.com/ChuMicro/ChuMicro/blob/main/INSTALL.md).

## Quick example

```python
from chumicro_sockets import connector

# One connect state machine per runtime.  Runner-shaped apps register
# the connector with the runner (it exposes check / handle / io_*);
# one-shot scripts drive it to terminal inline.  On CircuitPython pass
# radio=wifi.radio; the kwarg is ignored on MicroPython / CPython.
dial = connector("broker.example.com", 1883, radio=wifi.radio)
while dial.state not in ("ready", "failed"):
    dial.tick(0)
if dial.state == "failed":
    raise dial.last_error
sock = dial.socket
sock.send(b"PING\r\n")
buffer = bytearray(128)
nbytes = sock.recv_into(buffer, 128)
print(bytes(buffer[:nbytes]))
sock.close()

# TLS is a flag — `tls=True` verifies the cert chain on every runtime.
# Each runtime gets its trust roots from the right place:
# CircuitPython's firmware bundle, CPython's OS trust store,
# MicroPython's library-shipped bundle (override via
# `set_default_ca_bundle`).  Pass `context=ssl_context_no_verify()`
# for explicit opt-out.
dial = connector("api.example.com", 443, tls=True)
```

> **CircuitPython** always needs an explicit `radio=` — the socketpool is built from it (`socketpool.SocketPool(radio)`).  Pass `wifi.radio`, or whatever radio object your board exposes.  MicroPython and CPython ignore the kwarg.

For tests, `chumicro_sockets.testing.FakeSocket` implements the same
protocol against in-memory bytearrays so downstream libraries
(`chumicro-mqtt`, future `chumicro-requests`) can reach 94 % coverage
without hitting the network.

## What's included

| Symbol | Purpose |
|---|---|
| `connector(host, port, *, tls=False, context=None, radio=None)` | Non-blocking tick-driven TCP/TLS connect — the one connect state machine.  Register it with a runner or drive `tick()` to terminal inline. |
| `listener(host, port, *, tls=False, context=None, backlog=4, radio=None)` | Open a non-blocking TCP or TLS listening socket. |
| `udp_socket(bind_host="0.0.0.0", bind_port=0, *, radio=None, broadcast=False)` | Open a UDP datagram socket; default args bind ephemeral. |
| `ssl_context_with_ca(ca_pem)` | Build an `ssl.SSLContext` trusting only the supplied CA(s).  Works on every supported runtime. |
| `ssl_context_no_verify()` | Build an `ssl.SSLContext` that **skips** certificate verification.  Explicit opt-out — named so a reviewer can grep for it. |
| `set_default_ca_bundle(pem_bytes)` | Replace the CA bundle used by `connector(tls=True, context=None)` on MicroPython.  No-op on CP / CPython.  Pass `None` to revert to the library-shipped bundle. |
| `ssl_context_with_cert_and_key_paths(cert_path, key_path)` | Server-side `ssl.SSLContext` from PEM file paths.  CP-portable shape. |
| TCP socket surface (duck-typed) | `send`, `recv_into`, `close`, `setblocking`, `settimeout`.  Any object exposing these works; no named Protocol class is exported. |
| UDP socket surface (duck-typed) | `sendto(data, host, port)`, `recvfrom_into(buffer, nbytes=0) -> (n, (host, port))`, `close`, `setblocking`.  Any object exposing these works. |
| `UnsupportedSSLConfigError` | Raised when the requested TLS shape isn't supported by the current runtime (e.g. CP's in-memory cert+key). |
| `chumicro_sockets.testing.FakeSocket` / `FakeUDPSocket` | In-memory test doubles covering the full TCP / UDP protocol. |

## Where this fits

No runtime dependencies.  On CircuitPython the caller passes a radio (e.g. `wifi.radio`, or `chumicro-wifi`'s adapter radio) from which the socketpool is built.  Substrate for every networked library that follows: [`chumicro-requests`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/requests), [`chumicro-http-server`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/http_server), [`chumicro-mqtt`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/mqtt), [`chumicro-websockets`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/websockets), and [`chumicro-ntp`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/ntp).

## Platform support

Works on CPython, MicroPython, and CircuitPython.

## Examples

| Example | What it shows |
|---|---|
| [`tcp_roundtrip.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/sockets/examples/tcp_roundtrip.py) | Real TCP connect → send → recv → close.  Same shape on every runtime; pass `radio=wifi.radio` on CircuitPython. |
| [`tls_with_custom_ca.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/sockets/examples/tls_with_custom_ca.py) | Custom-CA TLS via `ssl_context_with_ca`.  Documents the substrate quirks observed on Pi Pico W mbedTLS in the docstring. |
| [`udp_echo_client.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/sockets/examples/udp_echo_client.py) | Board-side UDP echo client — wifi up, send datagram to a host echo server, read echo back, non-blocking.  Cross-runtime (CP + MP). |

## Contributing

Working on `chumicro-sockets` itself?  Clone the [mono-repo](https://github.com/ChuMicro/ChuMicro) if you haven't already — the rest of the workflow assumes you're inside that workspace.

```bash
pip install -e .[test]
pytest tests/                  # host-side tests
pytest functional_tests/       # on-device tests (needs a board registered in devices.yml)
```

Register a board before running functional tests: `chumicro-workspace add-device <id> --address <port>`.

## Docs

📖 **[Stable docs](https://chumicro.github.io/ChuMicro/sockets/stable/)** · **[Experimental docs](https://chumicro.github.io/ChuMicro/sockets/experimental/)**

## Find this library

- **PyPI:** [chumicro-sockets](https://pypi.org/project/chumicro-sockets/)
- **Bundle:** [ChuMicro-Bundle](https://github.com/ChuMicro/ChuMicro-Bundle/tree/main/chumicro_sockets) (CircuitPython & MicroPython)
- **Experimental bundle:** [ChuMicro-Bundle-Experimental](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental/tree/main/chumicro_sockets)
- **Source:** [libraries/sockets](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/sockets)

## License

[MIT](https://github.com/ChuMicro/ChuMicro/blob/main/LICENSE)
