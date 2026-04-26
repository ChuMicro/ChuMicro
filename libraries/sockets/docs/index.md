# chumicro-sockets

Cross-runtime TCP + TLS client sockets.  One protocol, one factory, runtime-appropriate adapters for CircuitPython (`socketpool`), MicroPython (`socket` + `ssl`), and CPython (stdlib).

## Quick example

```python
from chumicro_sockets import tcp_client_socket, tls_client_socket

sock = tcp_client_socket("broker.example.com", 1883, radio=wifi_radio_or_none)
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
