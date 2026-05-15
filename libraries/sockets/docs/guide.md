# User Guide

## Overview

`chumicro-sockets` provides a single TCP + TLS client API that works the same way on CircuitPython, MicroPython, and CPython.  The runtimes diverge in ways the library can't paper over — CircuitPython has no `socket` module, only `socketpool(radio)`; MicroPython has stdlib socket + mbedTLS-backed ssl on current builds; CPython has the full stdlib stack — so the library exposes one [`TCPClientSocket`](api.md#chumicro_sockets.TCPClientSocket) protocol and routes [`tcp_client_socket`](api.md#chumicro_sockets.tcp_client_socket) / [`tls_client_socket`](api.md#chumicro_sockets.tls_client_socket) to a runtime-appropriate adapter.

`chumicro-mqtt`, `chumicro-requests`, `chumicro-http-server`, and `chumicro-websockets` all build on this library; none of them import `socketpool`, `socket`, or `ssl` directly.

## Getting started

### Plain TCP

```python
from chumicro_sockets import tcp_client_socket

# CircuitPython requires `radio=wifi.radio`; MP / CPython ignore it.
sock = tcp_client_socket("broker.example.com", 1883, radio=None)
try:
    sock.send(b"PING\r\n")
    buffer = bytearray(128)
    nbytes = sock.recv_into(buffer, 128)
    print(bytes(buffer[:nbytes]))
finally:
    sock.close()
```

### TLS — default-secure on every runtime

```python
from chumicro_sockets import tls_client_socket

sock = tls_client_socket("api.example.com", 443, radio=None)
sock.send(b"GET / HTTP/1.0\r\n\r\n")
```

`context=None` verifies the cert chain on every runtime.  Each runtime gets its trust roots from the right place:

| Runtime | Source of trust roots |
|---|---|
| CircuitPython | Firmware-bundled mbedTLS CA store (`x509-crt-bundle`).  ~150 Mozilla NSS roots; built into the firmware. |
| CPython | `ssl.create_default_context()` — host OS trust store. |
| MicroPython | Library-shipped CA bundle (~16 KB DER, 17 high-coverage roots: Let's Encrypt, DigiCert, Amazon, Google, GlobalSign, Sectigo, GoDaddy/Starfield, Entrust, Microsoft).  A strict subset of CircuitPython's firmware bundle.  Override via [`set_default_ca_bundle`](api.md#chumicro_sockets.set_default_ca_bundle) for private CAs or broader coverage. |

For explicit no-verification (dev against self-signed brokers, captive-portal probes), pass `context=ssl_context_no_verify()` — the opt-out is named so a code reviewer can grep for it.

### TLS with a custom CA

```python
from chumicro_sockets import tls_client_socket, ssl_context_with_ca

with open("ca.pem", "rb") as ca_file:
    ca_pem = ca_file.read()

context = ssl_context_with_ca(ca_pem)
sock = tls_client_socket("api.example.com", 443, context=context, radio=None)
```

`ssl_context_with_ca` works on every supported runtime — chumicro's minimum supported board class (256 KB MCU RAM / 4 MB flash; Pi Pico W, ESP32-S2, ESP32-S3, ESP32-S3 Feather, plus any current-LTS MP/CPython host) all ships the on-board `ssl` module on current firmware, so the call shape is uniform.  Older legacy radios that lack the `ssl` module (AirLift, WIZNET5K-pre-mbedTLS) aren't in scope for this library; users on those boards should pin to the existing `adafruit_connection_manager` ecosystem instead.

### Non-blocking I/O

```python
import select

sock = tcp_client_socket("host", 1883, radio=None)
sock.setblocking(False)
poller = select.poll()
poller.register(sock.fileno(), select.POLLIN)

while True:
    for fd, event in poller.poll(timeout=100):
        if event & select.POLLIN:
            buffer = bytearray(256)
            try:
                nbytes = sock.recv_into(buffer, 256)
            except OSError as error:
                if error.args[0] == 11:  # EAGAIN
                    continue
                raise
            handle(bytes(buffer[:nbytes]))
```

`OSError(errno=11)` (`EAGAIN`) is the cross-runtime "would block" signal.  `fileno()` returns `-1` on adapters whose socket has no real fd (CP-radio fakes); callers that need polling should fall back to `settimeout`-based polling when `fileno() == -1`.

## Runner pattern

`chumicro-sockets` is a passive transport — it doesn't need its own `check()` / `handle()` lifecycle.  The downstream library that owns the connection (e.g. `chumicro-mqtt`) implements the runner contract and uses the socket as a non-blocking byte pipe inside `check()` and `handle()`.

## Memory notes

The socket itself doesn't allocate — the protocol surface is `recv_into(buffer, nbytes)` and `send(bytes_or_memoryview)` so callers control buffer lifetimes.  Pre-allocate one `bytearray` per connection and reuse it:

```python
RX_BUFFER = bytearray(256)

def read(sock):
    nbytes = sock.recv_into(RX_BUFFER, 256)
    return memoryview(RX_BUFFER)[:nbytes]
```

`FakeSocket` does keep an internal `bytearray(sent)` log — useful for tests, but don't hold the fake across long-running scenarios; replace it for each test.

## Platform notes

| Runtime | TCP | TLS context | Custom CA | `fileno()` |
|---|---|---|---|---|
| CPython | ✅ stdlib `socket` | ✅ `ssl.SSLContext` | ✅ via `ssl_context_with_ca` | ✅ real fd |
| MicroPython | ✅ stdlib `socket` | ✅ MP `ssl.SSLContext` (mbedTLS) | ✅ via `ssl_context_with_ca` | ✅ real fd |
| CircuitPython | ✅ `socketpool` + `radio` | ✅ on-board `ssl.SSLContext` | ✅ via `ssl_context_with_ca` | ⚠️ may return `-1` |

CircuitPython requires a `radio=` kwarg pointing at the board's wifi radio (typically `wifi.radio`).  MicroPython and CPython ignore the kwarg.

The TLS surface is uniform across runtimes because every supported board (256 KB MCU RAM / 4 MB flash, current-LTS firmware — Pi Pico W, ESP32-S2, ESP32-S3, ESP32-S3 Feather native wifi) ships the on-board `ssl` module.  Legacy radios without `ssl` (AirLift, WIZNET5K-pre-mbedTLS) aren't supported by this library.

### Runtime + chip quirks

Live-AP acceptance runs against the supported boards surfaced four limitations that aren't bugs in this library — they constrain how you build certs and shape your TLS handshakes:

| Runtime + chip | Quirk | Workaround |
|---|---|---|
| CircuitPython on rp2 (Pi Pico W / Pi Pico 2 W) — TLS *server* | `tls_listening_socket` raises `UnsupportedSSLConfigError` up-front. The CYW43 TLS handshake path raises `OSError(32)` mid-handshake AND wedges the chip's station-mode state until you unplug-and-replug USB power. | Use an ESP32-family board for HTTPS server, or run MicroPython on the same Pi Pico W (verified working). TLS *client* on CircuitPython rp2 is unaffected. |
| MicroPython on rp2 (Pi Pico W) | mbedTLS build rejects self-signed certs entirely (`ValueError('invalid cert')`) | Use a CA-signed cert.  For dev, skip TLS testing on this combo or use a real CA chain. |
| MicroPython SSLSocket on some ports | Wrapped TLS socket lacks `settimeout` / `setblocking` / `fileno` | Wrapper falls back to no-op + `fileno() = -1`; non-blocking semantics still hold via the TLS layer. |
| Stricter mbedTLS builds | Reject IP-only SAN certs | Generate certs with at least one DNS SAN.  On a LAN, `<hostname>.local` works via mDNS; set `server_hostname=` to that DNS name. |

Tested on real CircuitPython and MicroPython boards for both plain TCP and TLS before each release.

## Examples

| Example | What it shows |
|---|---|
| [`tcp_roundtrip.py`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/sockets/examples/tcp_roundtrip.py) | Real TCP connect → send → recv → close, runs identically on every runtime. |
| [`tls_with_custom_ca.py`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/sockets/examples/tls_with_custom_ca.py) | Custom-CA TLS via `ssl_context_with_ca`. |
| [`udp_echo_client.py`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/sockets/examples/udp_echo_client.py) | Board-side UDP echo client — wifi up, send datagram, read echo back.  Cross-runtime (CP + MP). |

---

<div class="chumicro-footer" markdown>

[← Home](index.md)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/sockets) · \
[PyPI](https://pypi.org/project/chumicro-sockets/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
