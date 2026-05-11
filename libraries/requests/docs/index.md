# chumicro-requests

**Non-blocking HTTP/1.1 client for CircuitPython, MicroPython, and CPython.**

An LED keeps blinking on the same board while a request is in flight, in a TLS handshake, or mid-timeout against a stalled peer.  Built on `chumicro-sockets` and `chumicro-timing`.

## Quick example

```python
from chumicro_requests import HttpClient, chumicro_sockets_factory
from chumicro_timing import ticks_ms

client = HttpClient(connection_factory=chumicro_sockets_factory(radio=wifi.radio))
handle = client.get("http://api.example.com/now", timeout_ms=5000)

while not handle.done:
    now = ticks_ms()
    if client.check(now):
        client.handle(now)

response = handle.result   # raises HttpError on failure
print(response.status_code, response.headers["content-type"])
print(response.text)       # decoded str (charset sniffed from Content-Type)
print(response.json())     # parsed JSON when Content-Type is application/json
```

## Documentation

- [User Guide](guide.md) — getting started and usage patterns
- [API Reference](api.md) — full API documentation
- [Testing Helpers](testing.md) — `FakeHttpClient` for downstream test suites

---

<div class="chumicro-footer" markdown>

[← All ChuMicro Libraries](../../)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/requests) · \
[PyPI](https://pypi.org/project/chumicro-requests/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
