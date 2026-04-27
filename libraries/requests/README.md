# chumicro-requests

<img src="https://raw.githubusercontent.com/ChuMicro/ChuMicro/main/support/docs/chumicro_tip.png"
align="left" width="64" style="margin-right: 16px; margin-bottom: 8px;">

Non-blocking HTTP/1.1 client for CircuitPython, MicroPython, and CPython.
Built on `chumicro-sockets` and `chumicro-timing` so an LED can keep
blinking on the same board while a request is in flight, in a TLS
handshake, or mid-timeout against a stalled peer.

<br clear="left">

> Part of the [ChuMicro](https://github.com/ChuMicro/ChuMicro) family — small, focused Python libraries for microcontrollers and laptops. [See all libraries.](https://github.com/ChuMicro/ChuMicro#whats-in-the-box)

## Installation

### CircuitPython ([circup](https://github.com/adafruit/circup))

circup is CircuitPython's package manager — it uses [bundles](https://learn.adafruit.com/keep-your-circuitpython-libraries-on-devices-up-to-date-with-circup/bundle-commands) to find third-party packages. Register the ChuMicro bundle once, then install by name:

```bash
circup bundle-add ChuMicro/ChuMicro-Bundle
circup install chumicro-requests
```

### MicroPython ([mip](https://docs.micropython.org/en/latest/reference/packages.html))

```bash
mpremote mip install github:ChuMicro/ChuMicro-Bundle/chumicro_requests
```

> **Want pre-compiled `.mpy` bytecode?** Add `mpy6/` before the package name for faster startup and lower RAM usage on boards with mpy format v6 (MicroPython 1.24+):
> ```
> mpremote mip install github:ChuMicro/ChuMicro-Bundle/mpy6/chumicro_requests
> ```

### CPython (pip)

```bash
pip install chumicro-requests
```

*Just getting started? Skip this — the install commands above are all you need.*

<details>
<summary>Experimental (pre-release) versions and channel switching</summary>

Pre-release builds are published automatically when a library version is bumped. Do not register both bundles simultaneously — circup may pick either version for a given package.

```bash
# CircuitPython — switch to experimental
circup bundle-remove ChuMicro/ChuMicro-Bundle              # skip if never added
circup bundle-add ChuMicro/ChuMicro-Bundle-Experimental
circup install chumicro-requests

# MicroPython
mpremote mip install github:ChuMicro/ChuMicro-Bundle-Experimental/chumicro_requests

# CPython
pip install chumicro-requests-experimental
```

</details>

## Quick example

```python
from chumicro_requests import HttpClient, chumicro_sockets_factory
from chumicro_timing import ticks_ms

client = HttpClient(connection_factory=chumicro_sockets_factory(radio=wifi.radio))
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

v1 scope (Decision 0040): plain HTTP GET (slice 3a) + body decode
(`.text` / `.json()` / charset sniff — slice 3b). HTTPS, POST,
redirects, and chunked transfer-encoding land in subsequent slices.

## Platform support

Works on CPython, MicroPython, and CircuitPython. Pure Python; depends only
on `chumicro-sockets` (TCP/TLS transport) and `chumicro-timing` (ticks).

## Examples

| Example | What it shows |
|---|---|
| `quickstart.py` | Plain HTTP GET against an in-memory `FakeSocket` — runs on any host without a network. |

## Developing this library

Host-side tests live in `tests/`; real-board functional tests belong in `functional_tests/`.

```bash
python scripts/run.py test --libraries requests
python scripts/run.py test-libraries-functional --library requests
```

Before running device tests, generate local board config files with `python scripts/run.py setup`, then fill in `devices.yml`. See the [contributing guide](https://github.com/ChuMicro/ChuMicro/blob/main/CONTRIBUTING.md) and the [device testing guide](https://github.com/ChuMicro/ChuMicro/blob/main/docs/contributing/device-testing.md) for the full workflow.

## Docs

📖 **[Stable docs](https://chumicro.github.io/ChuMicro/requests/stable/)** · **[Experimental docs](https://chumicro.github.io/ChuMicro/requests/experimental/)**

## Find this library

- **PyPI:** [chumicro-requests](https://pypi.org/project/chumicro-requests/)
- **Bundle:** [ChuMicro-Bundle](https://github.com/ChuMicro/ChuMicro-Bundle/tree/main/chumicro_requests) (CircuitPython & MicroPython)
- **Experimental bundle:** [ChuMicro-Bundle-Experimental](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental/tree/main/chumicro_requests)
- **Source:** [libraries/requests](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/requests)
