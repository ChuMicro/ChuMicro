# chumicro-sockets

**Cross-runtime TCP + TLS client sockets for CircuitPython, MicroPython, and CPython.**

One protocol, one factory, runtime-appropriate adapters underneath — CircuitPython's `socketpool`, MicroPython's `socket` + `ssl`, CPython's stdlib.

## Quick example

```python
from chumicro_sockets import tcp_client_socket

# On CircuitPython pass `radio=wifi.radio` here; MP / CPython ignore the kwarg.
sock = tcp_client_socket("broker.example.com", 1883, radio=None)
sock.send(b"PING\r\n")
buffer = bytearray(64)
nbytes = sock.recv_into(buffer, 64)
sock.close()
```

## Documentation

- [User Guide](guide.md) — getting started and usage patterns
- [API Reference](api.md) — full API documentation
- [Testing Helpers](testing.md) — fakes for downstream test suites

---

<div class="chumicro-footer" markdown>

[← All ChuMicro Libraries](../../)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/sockets) · \
[PyPI](https://pypi.org/project/chumicro-sockets/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
