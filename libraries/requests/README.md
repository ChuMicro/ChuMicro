# chumicro-requests

<img src="https://raw.githubusercontent.com/ChuMicro/ChuMicro/main/support/docs/chumicro_tip.png"
align="left" width="64" style="margin-right: 16px; margin-bottom: 8px;">

**A non-blocking HTTP/1.1 client — your LED keeps blinking through a TLS handshake.**

A `requests`-flavored surface that advances one chunk per runner tick — connect, send, recv, parse — so your control loop never stalls waiting for a peer.  Plain HTTP, HTTPS (live-verified on real boards), POST / PUT / PATCH / DELETE, JSON helper, redirect handling, and `Transfer-Encoding: chunked` decode.

<br clear="left">

> Part of the [ChuMicro](https://github.com/ChuMicro/ChuMicro) family — small, focused Python libraries for microcontrollers and laptops. [Browse all libraries.](https://github.com/ChuMicro/ChuMicro/tree/main/libraries)

## Install

```bash
# CircuitPython (after `circup bundle-add ChuMicro/ChuMicro-Bundle`)
circup install chumicro-requests

# MicroPython
mpremote mip install github:ChuMicro/ChuMicro-Bundle/chumicro_requests

# CPython
pip install chumicro-requests
```

For bundle setup, pre-compiled `.mpy` bundles, the experimental channel, and details on PyPI naming, see the [chumicro INSTALL guide](https://github.com/ChuMicro/ChuMicro/blob/main/INSTALL.md).

## Quick example

```python
from chumicro_requests import HttpClient
from chumicro_requests.sockets_factory import chumicro_sockets_factory
from chumicro_timing import ticks_ms

client = HttpClient(connection_factory=chumicro_sockets_factory())
handle = client.get("http://api.example.com/now", timeout_ms=5000)

while not handle.done:
    if client.check(ticks_ms()):
        client.handle(ticks_ms())

response = handle.result          # raises HttpError on failure
print(response.status_code)       # 200
print(response.headers["content-type"])
print(response.body)              # raw response bytes
print(response.text)              # decoded str (charset sniffed from Content-Type)
print(response.json())            # parsed JSON when Content-Type is application/json
```

## What's included

| Symbol | Purpose |
|---|---|
| `HttpClient` | Runner-shaped HTTP/1.1 client; `check(now_ms)` / `handle(now_ms)`. |
| `RequestHandle` | Per-request handle: `.done`, `.result`, `.error`. |
| `Response` | Status code, reason, headers, raw body, URL; `.text`, `.json()`, `.encoding`. |
| `CaseInsensitiveDict` | Header dict with case-insensitive lookups. |
| `WhenOversized` | Policy enum for responses past `max_body_bytes`. |
| `chumicro_requests.sockets_factory.chumicro_sockets_factory(...)` | Opt-in submodule: convenience connection-factory wired to chumicro-sockets. |
| `parse_url(url)` | URL → `(scheme, host, port, path)`. |
| `parse_charset(content_type)` | Extract charset from a Content-Type header value. |
| `encode_request(...)` | Build raw HTTP request bytes. |
| `ResponseParser` | Streaming response state machine. |
| `HttpError` + subclasses | `HttpBusyError`, `HttpTimeoutError`, `HttpProtocolError`, `HttpURLError`, `HttpOversizedError`. |
| `chumicro_requests.testing.FakeHttpClient` | Host-only fake for downstream test suites. |

## Where this fits

Depends on [`chumicro-sockets`](../sockets/) for TCP / TLS and [`chumicro-timing`](../timing/) for ticks.  Used directly in app code.

## Platform support

Works on CPython, MicroPython, and CircuitPython.  Pure Python — no native extensions.

## Examples

| Example | What it shows |
|---|---|
| `periodic_get.py` | Periodic GET on a real CP/MP board.  Brings wifi up, hits a configured URL every N seconds, prints status + body length, drives an LED-blink counter to verify the request never blocks the loop.  Reads wifi + target URL from `runtime_config.msgpack` (chumicro-workspace) with a constants fallback.  Cross-runtime (CP + MP). |

## Wiring wifi credentials for examples and functional tests

The hardware-prefixed examples + real-network suites in `functional_tests/test_real_*.py` need wifi credentials.  See [`docs/wiring-wifi-credentials.md`](https://github.com/ChuMicro/ChuMicro/blob/main/docs/wiring-wifi-credentials.md) for the workspace-based and raw single-file paths.  The library itself never reads TOML — it takes a `connection_factory` and goes; config wiring is application-layer.

## Contributing

Working on `chumicro-requests` itself?  Clone the [mono-repo](https://github.com/ChuMicro/ChuMicro) if you haven't already — the rest of the workflow assumes you're inside that workspace.

```bash
pip install -e .[test]
pytest tests/                  # host-side tests
pytest functional_tests/       # on-device tests (needs a board registered in devices.yml)
```

Register a board before running functional tests: `chumicro-workspace add-device <id> --address <port>`.

## Docs

📖 **[Stable docs](https://chumicro.github.io/ChuMicro/requests/stable/)** · **[Experimental docs](https://chumicro.github.io/ChuMicro/requests/experimental/)**

## Find this library

- **PyPI:** [chumicro-requests](https://pypi.org/project/chumicro-requests/)
- **Bundle:** [ChuMicro-Bundle](https://github.com/ChuMicro/ChuMicro-Bundle/tree/main/chumicro_requests) (CircuitPython & MicroPython)
- **Experimental bundle:** [ChuMicro-Bundle-Experimental](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental/tree/main/chumicro_requests)
- **Source:** [libraries/requests](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/requests)

## License

[MIT](https://github.com/ChuMicro/ChuMicro/blob/main/LICENSE)
