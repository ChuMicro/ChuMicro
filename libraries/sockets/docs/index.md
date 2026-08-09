# chumicro-sockets

**One TCP, TLS, and UDP socket surface across CircuitPython, MicroPython, and CPython.**

Three entry points cover the shapes a device needs: `connector` dials out, `listener` accepts inbound connections, and `udp_socket` sends and receives datagrams.  TLS is a `tls=` flag on each, and custom-CA trust and server-side certificates work the same way everywhere.  Underneath, each entry picks the runtime's own substrate (CircuitPython's `socketpool`, MicroPython's `socket` plus `ssl`, CPython's stdlib) so your code never names one.

## Quick example

```python
from chumicro_sockets import connector

# CircuitPython needs the board radio: with chumicro-wifi, pass
# radio=wifi.adapter.radio.  MicroPython and CPython ignore the argument.
dial = connector("broker.example.com", 1883, radio=None)
while dial.state not in ("ready", "failed"):  # or register with a runner
    dial.tick(0)
if dial.state == "failed":
    raise dial.last_error
sock = dial.socket
sock.send(b"PING\r\n")
buffer = bytearray(64)
nbytes = sock.recv_into(buffer, 64)
sock.close()
```

## Documentation

- [User Guide](guide.md): plain TCP, TLS defaults, TLS with a custom CA, driving a connector from a runner, per-runtime and per-chip quirks
- [API Reference](api.md): `connector` / `listener` / `udp_socket` and the SSL-context builders, plus the transport factories, the generator helpers, and the wait objects
- [Testing Helpers](testing.md): using `FakeSocket` in your tests

---

<div class="chumicro-footer" markdown>

[← All ChuMicro Libraries](../../)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/sockets) · \
[PyPI](https://pypi.org/project/chumicro-sockets/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
