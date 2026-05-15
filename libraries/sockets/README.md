# chumicro-sockets

<img src="https://raw.githubusercontent.com/ChuMicro/ChuMicro/main/support/docs/chumicro_tip.png"
align="left" width="64" style="margin-right: 16px; margin-bottom: 8px;">

**One TCP / TLS / UDP socket surface across CircuitPython, MicroPython, and CPython.**

One factory per socket shape (`tcp_client_socket`, `tls_client_socket`, `tcp_listening_socket`, `udp_socket`, …) hides the per-runtime adapter selection.  Custom-CA TLS, server-side certs, and an in-memory `FakeSocket` for downstream library tests are all included.

<br clear="left">

> Part of the [ChuMicro](https://github.com/ChuMicro/ChuMicro) family — small, focused Python libraries for microcontrollers and laptops. [Browse all libraries.](https://github.com/ChuMicro/ChuMicro/tree/main/libraries)

## Install

```bash
# CircuitPython (after `circup bundle-add ChuMicro/ChuMicro-Bundle`)
circup install chumicro-sockets

# MicroPython
mpremote mip install github:ChuMicro/ChuMicro-Bundle/chumicro_sockets

# CPython
pip install chumicro-sockets
```

For bundle setup, pre-compiled `.mpy` bundles, the experimental channel, and details on PyPI naming, see the [chumicro INSTALL guide](https://github.com/ChuMicro/ChuMicro/blob/main/INSTALL.md).

## Quick example

```python
from chumicro_sockets import tcp_client_socket, tls_client_socket

# Plain TCP — runtime picks the right adapter.  CP auto-detects
# `wifi.radio`; MP and CPython have no equivalent.  No kwarg needed.
sock = tcp_client_socket("broker.example.com", 1883)
sock.send(b"PING\r\n")
buffer = bytearray(128)
nbytes = sock.recv_into(buffer, 128)
print(bytes(buffer[:nbytes]))
sock.close()

# TLS — verifies the cert chain on every runtime.  Each runtime gets
# its trust roots from the right place: CircuitPython's firmware
# bundle, CPython's OS trust store, MicroPython's library-shipped
# bundle (override via `set_default_ca_bundle`).  Pass
# `context=ssl_context_no_verify()` for explicit opt-out.
sock = tls_client_socket("api.example.com", 443)
```

> **CP boards without a `wifi` module** (SAMD M0, etc.) still need an explicit `radio=` — pass whatever radio object your board exposes. The kwarg is also there for multi-radio prototypes that want to bypass the auto-detect.

For tests, `chumicro_sockets.testing.FakeSocket` implements the same
protocol against in-memory bytearrays so downstream libraries
(`chumicro-mqtt`, future `chumicro-requests`) can reach 94 % coverage
without hitting the network.

## What's included

| Symbol | Purpose |
|---|---|
| `tcp_client_socket(host, port, *, radio=None)` | Open a plain TCP connection. |
| `tls_client_socket(host, port, *, context=None, radio=None)` | Open a TLS connection. |
| `tcp_listening_socket(host, port, *, backlog=4, radio=None)` | Open a non-blocking TCP listening socket. |
| `tls_listening_socket(host, port, *, context, backlog=4, radio=None)` | Open a non-blocking TLS listening socket. |
| `udp_socket(bind_host="0.0.0.0", bind_port=0, *, radio=None, broadcast=False)` | Open a UDP datagram socket; default args bind ephemeral. |
| `ssl_context_with_ca(ca_pem)` | Build an `ssl.SSLContext` trusting only the supplied CA(s).  Works on every supported runtime. |
| `ssl_context_no_verify()` | Build an `ssl.SSLContext` that **skips** certificate verification.  Explicit opt-out — named so a reviewer can grep for it. |
| `set_default_ca_bundle(pem_bytes)` | Replace the CA bundle used by `tls_client_socket(context=None)` on MicroPython.  No-op on CP / CPython.  Pass `None` to revert to the library-shipped bundle. |
| `ssl_context_with_cert_and_key_paths(cert_path, key_path)` | Server-side `ssl.SSLContext` from PEM file paths.  CP-portable shape. |
| `TCPClientSocket` (Protocol) | TCP surface (`send`, `recv_into`, `close`, `setblocking`, `settimeout`, `fileno`). |
| `UDPSocket` (Protocol) | UDP surface (`sendto(data, host, port)`, `recvfrom_into(buffer, nbytes=0) -> (n, (host, port))`, `close`, `setblocking`, `settimeout`, `fileno`, `getsockname`). |
| `UnsupportedSSLConfigError` | Raised when the requested TLS shape isn't supported by the current runtime (e.g. CP's in-memory cert+key). |
| `chumicro_sockets.testing.FakeSocket` / `FakeUDPSocket` | In-memory test doubles covering the full TCP / UDP protocol. |

## Where this fits

Depends on [`chumicro-timing`](../timing/) for ticks; uses [`chumicro-wifi`](../wifi/)'s radio on CircuitPython for transport.  Substrate for every networked library that follows: [`chumicro-requests`](../requests/), [`chumicro-http-server`](../http_server/), [`chumicro-mqtt`](../mqtt/), [`chumicro-websockets`](../websockets/), and [`chumicro-ntp`](../ntp/).

## Platform support

Works on CPython, MicroPython, and CircuitPython.

## Examples

| Example | What it shows |
|---|---|
| [`tcp_roundtrip.py`](examples/tcp_roundtrip.py) | Real TCP connect → send → recv → close.  Same shape on every runtime; CP auto-detects `wifi.radio`. |
| [`tls_with_custom_ca.py`](examples/tls_with_custom_ca.py) | Custom-CA TLS via `ssl_context_with_ca`.  Documents the substrate quirks observed on Pi Pico W mbedTLS in the docstring. |
| [`udp_echo_client.py`](examples/udp_echo_client.py) | Board-side UDP echo client — wifi up, send datagram to a host echo server, read echo back, non-blocking.  Cross-runtime (CP + MP). |

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
