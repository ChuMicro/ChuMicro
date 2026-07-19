# chumicro-ntp

**Non-blocking SNTP client for CircuitPython, MicroPython, and CPython.**

Pure-Python, takes a UDP socket you provide, returns the server's transmit timestamp without blocking your tick loop.

## Quick example

```python
from chumicro_ntp import NTPClient
from chumicro_sockets import udp_socket
from chumicro_timing import ticks_ms

sock = udp_socket(radio=wifi.adapter.radio)
client = NTPClient(socket=sock, server="pool.ntp.org")
request = client.query()
while not request.done:
    now = ticks_ms()
    if client.check(now):
        client.handle(now)
print("unix seconds:", request.unix_seconds)
```

## Documentation

- [User Guide](guide.md) — getting started and usage patterns
- [API Reference](api.md) — full API documentation

---

<div class="chumicro-footer" markdown>

[← All ChuMicro Libraries](../../)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/ntp) · \
[PyPI](https://pypi.org/project/chumicro-ntp/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
