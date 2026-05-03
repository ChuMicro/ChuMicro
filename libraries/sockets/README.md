# chumicro-sockets

<img src="https://raw.githubusercontent.com/ChuMicro/ChuMicro/main/support/docs/chumicro_tip.png"
align="left" width="64" style="margin-right: 16px; margin-bottom: 8px;">

Cross-runtime TCP + TLS + UDP sockets for CircuitPython, MicroPython, and CPython.  One protocol per shape, one factory each, runtime-appropriate adapters underneath.

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

# TLS with the runtime's default CA store.
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
| `ssl_context_with_cert_and_key_paths(cert_path, key_path)` | Server-side `ssl.SSLContext` from PEM file paths.  CP-portable shape. |
| `TCPClientSocket` (Protocol) | TCP surface (`send`, `recv_into`, `close`, `setblocking`, `settimeout`, `fileno`). |
| `UDPSocket` (Protocol) | UDP surface (`sendto(data, host, port)`, `recvfrom_into(buffer, nbytes=0) -> (n, (host, port))`, `close`, `setblocking`, `settimeout`, `fileno`, `getsockname`). |
| `UnsupportedSSLConfigError` | Raised when the requested TLS shape isn't supported by the current runtime (e.g. CP's in-memory cert+key). |
| `chumicro_sockets.testing.FakeSocket` / `FakeUDPSocket` | In-memory test doubles covering the full TCP / UDP protocol. |

## Platform support

Works on CPython, MicroPython, and CircuitPython.

## Examples

| Example | What it shows |
|---|---|
| [`quickstart.py`](examples/quickstart.py) | FakeSocket round-trip — send/recv/close exercising the protocol against in-memory bytearrays. Identical on every runtime. |
| [`tcp_roundtrip.py`](examples/tcp_roundtrip.py) | Real TCP connect → send → recv → close.  Same shape on every runtime; CP auto-detects `wifi.radio`. |
| [`tls_with_custom_ca.py`](examples/tls_with_custom_ca.py) | Custom-CA TLS via `ssl_context_with_ca`.  Documents the substrate quirks observed on Pi Pico W mbedTLS in the docstring. |
| [`udp_echo_loopback.py`](examples/udp_echo_loopback.py) | Two UDP sockets on loopback — one-shot send/echo round trip.  Runs on CPython directly; same shape on a board (CP auto-detects `wifi.radio`). |
| [`circuitpython_udp_echo_client.py`](examples/circuitpython_udp_echo_client.py) | Board-side UDP echo client — wifi up, send datagram to a host echo server, read echo back, non-blocking. |

## Developing this library

Host-side tests live in `tests/`; real-board functional tests belong in `functional_tests/`.

```bash
python scripts/run.py test --libraries sockets
python scripts/run.py test-libraries-functional --library sockets
```

Before running device tests, generate local board config files with `python scripts/run.py setup`, then fill in `devices.yml`. See the [contributing guide](https://github.com/ChuMicro/ChuMicro/blob/main/CONTRIBUTING.md) and the [device testing guide](https://github.com/ChuMicro/ChuMicro/blob/main/docs/contributing/device-testing.md) for the full workflow.

## Docs

📖 **[Stable docs](https://chumicro.github.io/ChuMicro/sockets/stable/)** · **[Experimental docs](https://chumicro.github.io/ChuMicro/sockets/experimental/)**

## Find this library

- **PyPI:** [chumicro-sockets](https://pypi.org/project/chumicro-sockets/)
- **Bundle:** [ChuMicro-Bundle](https://github.com/ChuMicro/ChuMicro-Bundle/tree/main/chumicro_sockets) (CircuitPython & MicroPython)
- **Experimental bundle:** [ChuMicro-Bundle-Experimental](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental/tree/main/chumicro_sockets)
- **Source:** [libraries/sockets](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/sockets)
