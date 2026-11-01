# chumicro-sockets

<img src="https://raw.githubusercontent.com/ChuMicro/ChuMicro/main/support/docs/chumicro_tip.png"
align="left" width="64" style="margin-right: 16px; margin-bottom: 8px;">

**TCP, TLS, and UDP sockets that work the same way on CircuitPython, MicroPython, and CPython.**

`connector` opens a connection to a server, `listener` accepts connections from other devices, and `udp_socket` sends and receives single messages.  Each one picks the runtime's own networking modules (CircuitPython's `socketpool`, MicroPython's `socket` and `ssl`, CPython's standard library), so one program runs on all three.  `tls=True` turns on encryption.

<br clear="left">

> Part of the [ChuMicro](https://github.com/ChuMicro/ChuMicro) family: small, focused Python libraries for microcontrollers and laptops. [Browse all libraries.](https://github.com/ChuMicro/ChuMicro/tree/main/libraries)

## Install

```bash
# CircuitPython (after `circup bundle-add ChuMicro/ChuMicro-Bundle`)
circup install chumicro_sockets

# MicroPython
mpremote mip install github:ChuMicro/ChuMicro-Bundle/chumicro_sockets

# CPython
pip install chumicro-sockets
```

[Start here](https://chumicro.com/ChuMicro/guides/start-here/) takes a new board from flashing CircuitPython or MicroPython to running your own blink.  [Installing libraries](https://chumicro.com/ChuMicro/guides/install/) covers registering the bundle, the pre-compiled `.mpy` packages, the experimental channel, and why package names use a hyphen on PyPI and an underscore on the board.

## Quick example

Fetch a web page every 30 seconds, forever.  A failed attempt prints the error, and the next one runs on schedule:

```python
import time

from chumicro_sockets import connector

# CircuitPython needs the wifi radio: `import wifi`, then radio = wifi.radio.
# MicroPython and CPython ignore radio, so None works there.
radio = None

buffer = bytearray(256)

while True:
    # connector() returns at once.  Each tick() takes the next step (look up
    # the address, then connect) until the state is "ready" or "failed".
    dial = connector("example.com", 80, radio=radio)
    while dial.state not in ("ready", "failed"):
        dial.tick(0)  # a connector keeps no deadlines, so any time in ms works
        time.sleep(0.01)

    if dial.state == "failed":
        print(f"connect failed: {dial.last_error!r}")
    else:
        sock = dial.socket
        try:
            sock.settimeout(5)  # wait at most 5 s on each send and read
            sock.send(b"GET / HTTP/1.0\r\nHost: example.com\r\n\r\n")
            count = sock.recv_into(buffer)
            first_line = bytes(buffer[:count]).split(b"\r\n")[0]
            print(f"reply: {first_line.decode()}")
        except OSError as error:
            print(f"send or receive failed: {error!r}")
        sock.close()

    time.sleep(30)
```

For an encrypted connection, add `tls=True`: `connector("example.com", 443, tls=True, radio=radio)` checks the server's certificate against the runtime's trusted certificate authorities.  `ssl_context_with_ca` swaps in your own authority, for a server on your home network.

This loop waits on each step, which suits a board with one job.  On a board with other work, `runner.add(dial)` hands the connector to a [`chumicro-runner`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/runner) `Runner`, and the other work runs between the connector's steps.

## What's included

| Symbol | Description |
|---|---|
| `connector(host, port, *, tls=False, context=None, radio=None)` | Open a TCP or TLS connection one step at a time.  Call `tick()` until `state` is `"ready"` or `"failed"`, or hand it to a `Runner`.  `socket` holds the connection once ready.  `last_error` holds the reason after a failure.  `cancel()` gives up |
| `listener(host, port, *, tls=False, context=None, backlog=4, radio=None)` | Listen for incoming TCP or TLS connections.  `accept()` returns at once, raising `OSError` with `EAGAIN` when nobody is waiting |
| `udp_socket(bind_host="0.0.0.0", bind_port=0, *, radio=None, broadcast=False)` | Open a UDP socket.  The defaults pick any free local port |
| `ssl_context_with_ca(ca_pem)` | Build a TLS context that trusts the CA certificates you pass in.  On a board, they replace the built-in list |
| `ssl_context_no_verify()` | Build a TLS context that **skips** certificate checks.  The explicit name makes every use easy to find in review |
| `set_default_ca_bundle(pem_bytes)` | Replace the CA list `connector(tls=True)` trusts on MicroPython.  `None` restores the bundled list.  No effect on CircuitPython or CPython |
| `ssl_context_with_cert_and_key_paths(cert_path, key_path)` | Build a server-side TLS context from certificate and key files.  Works on every runtime |
| `ssl_context_with_cert_and_key(cert_pem, key_pem)` | Build a server-side TLS context from certificate and key bytes in memory.  MicroPython and CPython only |
| Connected TCP socket | `send`, `recv_into`, `close`, `setblocking`, and `settimeout`, on every runtime |
| UDP socket | `sendto(data, host, port)`, `recvfrom_into(buffer, nbytes=0)` returning `(count, (host, port))`, `close`, and `setblocking` |
| `UnsupportedSSLConfigError` | Raised when the runtime cannot build the TLS setup you asked for, such as an in-memory server key on CircuitPython |
| `chumicro_sockets.testing` | `FakeSocket`, `FakeUDPSocket`, and `FakeSocketConnector` answer the same calls from in-memory buffers, so code that talks over a socket runs under pytest with no network |

## Where this fits

Needs no other library.  The ChuMicro network libraries build on it: [`chumicro-requests`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/requests), [`chumicro-http-server`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/http_server), [`chumicro-mqtt`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/mqtt), [`chumicro-websockets`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/websockets), and [`chumicro-ntp`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/ntp).

## Platform support

Works on CPython, MicroPython, and CircuitPython.

### CircuitPython needs `radio=`

CircuitPython needs `radio=` on every `connector`, `listener`, and `udp_socket` call, because its sockets come from `socketpool.SocketPool(radio)`.  Pass `wifi.radio` from the built-in `wifi` module, or `wifi.adapter.radio` from a [`chumicro-wifi`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/wifi) `WifiService`.  MicroPython and CPython ignore the argument.

## Examples

| Example | What it shows |
|---|---|
| [`tcp_roundtrip.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/sockets/examples/tcp_roundtrip.py) | Every 30 seconds, connect to example.com, send an HTTP request, print the first line of the reply, and close.  CircuitPython and MicroPython |
| [`tls_with_custom_ca.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/sockets/examples/tls_with_custom_ca.py) | The same round trip over TLS, trusting only the one CA certificate pasted into the file.  The docstring covers pointing it at your own server.  CircuitPython |
| [`udp_echo_client.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/sockets/examples/udp_echo_client.py) | Every 5 seconds, send a numbered message to an echo server on your laptop and print the reply, in a loop that never waits on the network.  CircuitPython and MicroPython |

### Running the examples

Each example joins wifi through `helpers.py`, which sits beside it in `examples/`.  Set `WIFI_SSID` and `WIFI_PASSWORD` at the top of the example.  Copy the example to the board as `code.py` on CircuitPython or `main.py` on MicroPython, together with `helpers.py` and the libraries it imports.  From a clone of the [ChuMicro repository](https://github.com/ChuMicro/ChuMicro), `chumicro-workspace deploy-example sockets tcp_roundtrip` does the copying and takes the wifi settings from `secrets.toml`.  [Wiring wifi credentials](https://chumicro.com/ChuMicro/guides/wiring-wifi-credentials/) walks through both ways.

## Contributing

Issues, bug reports, and pull requests are welcome, and so is "I ran it on this board and here's what happened", some of the most useful feedback a hardware project can get.  Development happens in the [ChuMicro repository](https://github.com/ChuMicro/ChuMicro), whose contributing guide covers setup and the test workflow.

## Docs

📖 **[Stable docs](https://chumicro.com/ChuMicro/sockets/stable/)** · **[Experimental docs](https://chumicro.com/ChuMicro/sockets/experimental/)**

## Find this library

- **PyPI:** [chumicro-sockets](https://pypi.org/project/chumicro-sockets/)
- **Bundle:** [ChuMicro-Bundle](https://github.com/ChuMicro/ChuMicro-Bundle/tree/main/chumicro_sockets) (CircuitPython & MicroPython)
- **Experimental bundle:** [ChuMicro-Bundle-Experimental](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental/tree/main/chumicro_sockets)
- **Source:** [libraries/sockets](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/sockets)

## License

[MIT](https://github.com/ChuMicro/ChuMicro/blob/main/LICENSE)
