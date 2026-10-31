---
title: "chumicro-sockets: TCP, TLS, and UDP for CircuitPython and MicroPython"
---

# chumicro-sockets

**TCP, TLS, and UDP sockets that work the same way on CircuitPython, MicroPython, and CPython.**

Three functions cover what a board does on a network: `connector` opens a connection to a server, `listener` accepts connections from other devices, and `udp_socket` sends and receives single messages.  Each one picks the runtime's own networking modules for you (CircuitPython's `socketpool`, MicroPython's `socket` and `ssl`, CPython's standard library), so one program runs on all three.  Encryption is one argument: `tls=True`.

## Install

```bash
# CircuitPython (after `circup bundle-add ChuMicro/ChuMicro-Bundle`)
circup install chumicro_sockets

# MicroPython
mpremote mip install github:ChuMicro/ChuMicro-Bundle/chumicro_sockets

# CPython
pip install chumicro-sockets
```

No board running yet?  [Start here](https://chumicro.com/ChuMicro/guides/start-here/) goes from a new board to your own code running on it.  [Installing libraries](https://chumicro.com/ChuMicro/guides/install/) covers registering the bundle, the experimental channel, and the pre-compiled `.mpy` packages.

## Quick example

Fetch a web page every 30 seconds, forever.  A failed attempt prints the error and the next one runs on schedule.

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
        dial.tick(0)  # the time in ms; a connector keeps no deadlines, so 0 works
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

## Documentation

- [User Guide](guide.md): the connect loop step by step, choosing how a socket waits, TLS and your own certificate authority, UDP, accepting connections, running alongside other work with a runner, and per-runtime and per-chip notes
- [API Reference](api.md): `connector` / `listener` / `udp_socket` and the TLS context builders, plus the transport factories, the generator helpers, and the wait objects
- [Testing Helpers](testing.md): testing your socket code with `FakeSocket`, `FakeUDPSocket`, and `FakeSocketConnector`

---

<div class="chumicro-footer" markdown>

[← All ChuMicro Libraries](../../)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/sockets) · \
[PyPI](https://pypi.org/project/chumicro-sockets/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
