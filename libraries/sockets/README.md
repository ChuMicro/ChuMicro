# chumicro-sockets

<img src="https://raw.githubusercontent.com/ChuMicro/ChuMicro/main/support/docs/chumicro_tip.png"
align="left" width="64" style="margin-right: 16px; margin-bottom: 8px;">

Cross-runtime TCP + TLS client sockets for CircuitPython, MicroPython, and CPython.  One protocol, one factory, runtime-appropriate adapters underneath.

<br clear="left">

> Part of the [ChuMicro](https://github.com/ChuMicro/ChuMicro) family — small, focused Python libraries for microcontrollers and laptops. [See all libraries.](https://github.com/ChuMicro/ChuMicro#whats-in-the-box)

## Installation

### CircuitPython ([circup](https://github.com/adafruit/circup))

circup is CircuitPython's package manager — it uses [bundles](https://learn.adafruit.com/keep-your-circuitpython-libraries-on-devices-up-to-date-with-circup/bundle-commands) to find third-party packages. Register the ChuMicro bundle once, then install by name:

```bash
circup bundle-add ChuMicro/ChuMicro-Bundle
circup install chumicro-sockets
```

### MicroPython ([mip](https://docs.micropython.org/en/latest/reference/packages.html))

```bash
mpremote mip install github:ChuMicro/ChuMicro-Bundle/chumicro_sockets
```

> **Want pre-compiled `.mpy` bytecode?** Add `mpy6/` before the package name for faster startup and lower RAM usage on boards with mpy format v6 (MicroPython 1.24+):
> ```
> mpremote mip install github:ChuMicro/ChuMicro-Bundle/mpy6/chumicro_sockets
> ```

### CPython (pip)

```bash
pip install chumicro-sockets
```

*Just getting started? Skip this — the install commands above are all you need.*

<details>
<summary>Experimental (pre-release) versions and channel switching</summary>

Pre-release builds are published automatically when a library version is bumped. Do not register both bundles simultaneously — circup may pick either version for a given package.

```bash
# CircuitPython — switch to experimental
circup bundle-remove ChuMicro/ChuMicro-Bundle              # skip if never added
circup bundle-add ChuMicro/ChuMicro-Bundle-Experimental
circup install chumicro-sockets

# MicroPython
mpremote mip install github:ChuMicro/ChuMicro-Bundle-Experimental/chumicro_sockets

# CPython
pip install chumicro-sockets-experimental
```

</details>

## Quick example

```python
from chumicro_sockets import tcp_client_socket, tls_client_socket

# Plain TCP — runtime picks the right adapter.  CircuitPython
# requires `radio=wifi.radio`; MP and CPython ignore the kwarg.
sock = tcp_client_socket("broker.example.com", 1883, radio=None)
sock.send(b"PING\r\n")
buffer = bytearray(128)
nbytes = sock.recv_into(buffer, 128)
print(bytes(buffer[:nbytes]))
sock.close()

# TLS with the runtime's default CA store.
sock = tls_client_socket("api.example.com", 443, radio=None)
```

For tests, `chumicro_sockets.testing.FakeSocket` implements the same
protocol against in-memory bytearrays so downstream libraries
(`chumicro-mqtt`, future `chumicro-requests`) can reach 94 % coverage
without hitting the network.

## What's included

| Symbol | Purpose |
|---|---|
| `tcp_client_socket(host, port, *, radio=None)` | Open a plain TCP connection. |
| `tls_client_socket(host, port, *, context=None, radio=None)` | Open a TLS connection. |
| `ssl_context_with_ca(ca_pem)` | Build an `ssl.SSLContext` trusting only the supplied CA(s). Works on every supported runtime. |
| `TCPClientSocket` (Protocol) | The minimum surface every adapter implements (`send`, `recv_into`, `close`, `setblocking`, `settimeout`, `fileno`). |
| `UnsupportedSSLConfigError` | Reserved for future adapter additions; today's boards (Pi Pico W, ESP32-S2/S3 native wifi) don't raise it. |
| `chumicro_sockets.testing.FakeSocket` | In-memory test double covering the full protocol. |

## Platform support

Works on CPython, MicroPython, and CircuitPython.

## Examples

| Example | What it shows |
|---|---|
| [`quickstart.py`](examples/quickstart.py) | FakeSocket round-trip — send/recv/close exercising the protocol against in-memory bytearrays. Identical on every runtime. |
| [`tcp_roundtrip.py`](examples/tcp_roundtrip.py) | Real TCP connect → send → recv → close.  Same shape on CP/MP/CPython; CP needs `radio=wifi.radio`, MP/CPython ignore. |
| [`tls_with_custom_ca.py`](examples/tls_with_custom_ca.py) | Custom-CA TLS via `ssl_context_with_ca`.  Documents the substrate quirks observed on Pi Pico W mbedTLS in the docstring. |

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
