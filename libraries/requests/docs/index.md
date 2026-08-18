---
title: "chumicro-requests: non-blocking HTTP client for CircuitPython and MicroPython"
---

# chumicro-requests

**Non-blocking HTTP/1.1 client for CircuitPython, MicroPython, and CPython.**

An LED keeps blinking on the same board while a request is in flight, in a TLS handshake, or mid-timeout against a stalled peer.  Built on `chumicro-sockets` and `chumicro-timing`.

## Quick example

```python
from chumicro_requests import HttpClient
from chumicro_sockets.sockets_factory import connector_factory
from chumicro_timing import ticks_ms
from chumicro_wifi import WifiConfig, WifiService

wifi = WifiService(WifiConfig(ssid="home-wifi", password="s3cret"))
client = HttpClient(transport_factory=connector_factory(radio=wifi.adapter.radio))
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

`wifi.adapter.radio` is the board radio on CircuitPython and `None` on MicroPython and CPython, where the connector needs no radio.  Bringing your own socket instead of `chumicro-sockets` works too: `transport_factory` takes any `(host, port, use_tls)` callable.

## Documentation

- [User Guide](guide.md): generator flows and the `HttpClient` service, the POST / PUT / PATCH / DELETE verbs, redirects, body framing and decoding, streaming large bodies, bringing your own transport
- [API Reference](api.md): `HttpClient`, `RequestHandle`, and `Response`, plus the `yield from` generator helpers
- [Testing Helpers](testing.md): using `FakeHttpClient` in your tests

---

<div class="chumicro-footer" markdown>

[← All ChuMicro Libraries](../../)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/requests) · \
[PyPI](https://pypi.org/project/chumicro-requests/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
