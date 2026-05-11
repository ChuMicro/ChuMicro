# chumicro-requests

<img src="https://raw.githubusercontent.com/ChuMicro/ChuMicro/main/support/docs/chumicro_tip.png"
align="left" width="64" style="margin-right: 16px; margin-bottom: 8px;">

Non-blocking HTTP/1.1 client for CircuitPython, MicroPython, and CPython.
Built on `chumicro-sockets` and `chumicro-timing` so an LED can keep
blinking on the same board while a request is in flight, in a TLS
handshake, or mid-timeout against a stalled peer.

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
from chumicro_requests import HttpClient, chumicro_sockets_factory
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
| `chumicro_sockets_factory(...)` | Convenience connection-factory wired to chumicro-sockets. |
| `parse_url(url)` | URL → `(scheme, host, port, path)`. |
| `parse_charset(content_type)` | Extract charset from a Content-Type header value. |
| `encode_request(...)` | Build raw HTTP request bytes. |
| `ResponseParser` | Streaming response state machine. |
| `HttpError` + subclasses | `HttpBusyError`, `HttpTimeoutError`, `HttpProtocolError`, `HttpURLError`, `HttpOversizedError`. |
| `chumicro_requests.testing.FakeHttpClient` | Host-only fake for downstream test suites. |

v1 ships: plain HTTP GET, body decode + `.text` / `.json()` / charset
sniff, HTTPS via TLS (live-verified on Pi Pico W), POST + PUT + PATCH +
DELETE + JSON helper, 301 / 302 / 303 / 307 / 308 redirects with
per-request budget, and `Transfer-Encoding: chunked` decode.

## Platform support

Works on CPython, MicroPython, and CircuitPython. Pure Python; depends only
on `chumicro-sockets` (TCP/TLS transport) and `chumicro-timing` (ticks).

## Examples

| Example | What it shows |
|---|---|
| `periodic_get.py` | Periodic GET on a real CP/MP board.  Brings wifi up, hits a configured URL every N seconds, prints status + body length, drives an LED-blink counter to verify the request never blocks the loop.  Reads wifi + target URL from `runtime_config.msgpack` (chumicro-workspace) with a constants fallback.  Cross-runtime (CP + MP). |

## Configuring wifi for examples and functional tests

Real-network functional tests in `functional_tests/test_real_*.py` and the hardware-prefixed examples in `examples/circuitpython_*.py` need wifi credentials.  Two paths, depending on whether you're using a `chumicro-workspace`:

* **With a workspace (recommended).**  Put wifi creds in your workspace's gitignored `workspace.yml`, run `chumicro-workspace deploy <project>`, and the example reads them via `chumicro_config.load_runtime_config()`.
* **Raw single-file deploy** (no workspace).  Edit the `WIFI_SSID` / `WIFI_PASSWORD` constants near the top of the example file before copying it to `/code.py` (CP) or `/main.py` (MP).  The constants are the fallback when no `runtime_config.msgpack` is present.

The library itself never reads either source — it takes a `connection_factory` and goes.  The config wiring is application-layer; see `chumicro-config` + `chumicro-wifi` for the standard pattern.

## Developing this library

Host-side tests live in `tests/`; real-board functional tests belong in `functional_tests/`.

```bash
pip install -e .[test]
pytest tests/
pytest functional_tests/   # needs a registered board in devices.yml
```

Before running functional tests, register a board with `chumicro-workspace add-device <id> --address <port>`.

## Docs

📖 **[Stable docs](https://chumicro.github.io/ChuMicro/requests/stable/)** · **[Experimental docs](https://chumicro.github.io/ChuMicro/requests/experimental/)**

## Find this library

- **PyPI:** [chumicro-requests](https://pypi.org/project/chumicro-requests/)
- **Bundle:** [ChuMicro-Bundle](https://github.com/ChuMicro/ChuMicro-Bundle/tree/main/chumicro_requests) (CircuitPython & MicroPython)
- **Experimental bundle:** [ChuMicro-Bundle-Experimental](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental/tree/main/chumicro_requests)
- **Source:** [libraries/requests](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/requests)
