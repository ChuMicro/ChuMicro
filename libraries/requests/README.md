# chumicro-requests

<img src="https://raw.githubusercontent.com/ChuMicro/ChuMicro/main/support/docs/chumicro_tip.png"
align="left" width="64" style="margin-right: 16px; margin-bottom: 8px;">

**Fetch web pages and call web APIs from your board while your main loop keeps running.**

With `adafruit_requests`, `response = requests.get(url)` holds your program on that line until the server answers, so your LED stops blinking and button presses wait for as long as the server takes.  With `chumicro-requests`, `client.get(url)` returns a request handle at once.  Your `while True` loop calls `client.handle(now_ms)` on each pass.  Each call moves the request one small step and returns, and `request.done` turns `True` when the response is in.

The client speaks HTTP and HTTPS, sends GET, POST, PUT, PATCH, and DELETE (with a `json=` shortcut), follows redirects, and decodes chunked responses.  For a body bigger than RAM, such as a firmware image, `stream=True` hands it to you a piece at a time through a buffer you own.

<br clear="left">

> Part of the [ChuMicro](https://github.com/ChuMicro/ChuMicro) family: small, focused Python libraries for microcontrollers and laptops. [Browse all libraries.](https://github.com/ChuMicro/ChuMicro/tree/main/libraries)

## Install

```bash
# CircuitPython (after `circup bundle-add ChuMicro/ChuMicro-Bundle`)
circup install chumicro_requests

# MicroPython
mpremote mip install github:ChuMicro/ChuMicro-Bundle/chumicro_requests

# CPython
pip install chumicro-requests
```

For bundle setup, pre-compiled `.mpy` bundles, the experimental channel, and details on PyPI naming, see the [ChuMicro install guide](https://chumicro.com/ChuMicro/guides/install/).

## Quick example

A CircuitPython `code.py` that fetches a page every 30 seconds.  Put your network name and password in the `connect()` call.

```python
import wifi
from chumicro_requests import HttpClient
from chumicro_sockets.sockets_factory import connector_factory
from chumicro_timing import Rate, ticks_ms

wifi.radio.connect("your-network", "your-password")
client = HttpClient(transport_factory=connector_factory(radio=wifi.radio))
every_30_s = Rate(30_000, ticks_ms())
request = client.get("http://example.com/")  # starts the fetch and returns at once

while True:
    now_ms = ticks_ms()
    if client.check(now_ms):    # True while a request is in flight
        client.handle(now_ms)   # one small step: connect, send, or read

    if request is not None and request.done:
        if request.error is not None:
            print("failed:", request.error)
        else:
            print(request.response.status_code, len(request.response.body), "bytes")
        request = None

    if request is None and every_30_s.due(now_ms):
        request = client.get("http://example.com/")
```

On MicroPython, join wifi with `network.WLAN` as usual and call `connector_factory()` with no `radio`.

`request.response` holds what came back: `status_code`, `headers`, `body` (raw bytes), `text` (decoded), and `json()`.  A failed request sets `request.error` instead, an `HttpError` that says what went wrong: no answer within 10 seconds, a refused connection, a reply that is not valid HTTP.

To write the fetch as one line that reads like `adafruit_requests` code, see [`generator_fetch.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/requests/examples/generator_fetch.py): it does the same job with `response = yield from get(connector, url)` inside a generator function, driven by a `Runner` from `chumicro-runner`.

## What's included

| Symbol | Purpose |
|---|---|
| `HttpClient` | Makes requests: `get`, `post`, `put`, `patch`, `delete`, or `request(method, url)`.  Call `check(now_ms)` and `handle(now_ms)` from your loop to move the request in flight forward; `cancel()` abandons it. |
| `RequestHandle` | What `get()` and the other verbs return: `.done`, `.response`, `.error`, and `.result` (the response, or the error raised).  `.read_body_into(buffer)` reads a `stream=True` body. |
| `Response` | `status_code`, `reason`, `headers`, `body` (bytes), `url`; `.text`, `.json()`, and a settable `.encoding`. |
| `chumicro_requests.generators` | `get`, `post`, `put`, `patch`, `delete`, and `fetch` for `response = yield from get(...)` code driven by a `Runner`, plus `stream` for reading a large body a piece at a time. |
| `chumicro_sockets.sockets_factory.connector_factory(radio=..., ssl_context=...)` | Builds the `transport_factory` that `HttpClient` opens its connections through. |
| `CaseInsensitiveDict` | The header dict: `headers["content-type"]` and `headers["Content-Type"]` find the same entry. |
| `WhenOversized` | What happens to a body bigger than `max_body_bytes`: dropped quietly, dropped with an `on_oversized` call, or the request fails. |
| `HttpError` and subclasses | `HttpTimeoutError`, `HttpProtocolError`, `HttpURLError`, `HttpOversizedError`, and `HttpBusyError` (a second request started while one is in flight). |
| `parse_url`, `parse_charset`, `encode_request`, `ResponseParser` | The HTTP/1.1 pieces `HttpClient` is built from, for code that frames its own requests. |
| `chumicro_requests.testing.FakeHttpClient` | A stand-in client for your host tests: script the responses, no network needed. |

## Where this fits

Depends on [`chumicro-sockets`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/sockets) for TCP and TLS connections and [`chumicro-timing`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/timing) for millisecond ticks.  Used directly in app code.

## Platform support

Works on CircuitPython, MicroPython, and CPython.  Pure Python, no native extensions.

On a board, opening the connection holds your loop until it finishes: the DNS lookup, the TLS handshake for an `https://` URL, and on CircuitPython the TCP connect as well.  A slow or unreachable host can hold it for seconds.  Everything after that (sending the request, waiting for the server, reading the response) runs one small step per `handle()` call.

## Examples

| Example | What it shows |
|---|---|
| [`periodic_get.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/requests/examples/periodic_get.py) | Fetches a page every 30 seconds from a plain `while True` loop that calls `client.check` and `client.handle`, and prints the status and size of each answer.  CircuitPython and MicroPython. |
| [`generator_fetch.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/requests/examples/generator_fetch.py) | The same job written as `response = yield from get(...)` in a generator function, run by a `Runner` loop.  CircuitPython and MicroPython. |

## Running the examples

Both examples join wifi through `helpers.py`, which sits beside them in `examples/`.  Set `WIFI_SSID` and `WIFI_PASSWORD` at the top of the example, then copy it to your board as `code.py` (CircuitPython) or `main.py` (MicroPython) together with `helpers.py` and the libraries it imports.  With `chumicro-workspace`, `chumicro-workspace deploy-example requests periodic_get` does the copying and fills in the wifi details from your `secrets.toml`.  [Wiring wifi credentials](https://chumicro.com/ChuMicro/guides/wiring-wifi-credentials/) walks through both.

The library itself never reads wifi settings: `HttpClient` takes a `transport_factory` and nothing else, so credentials stay in your code.

## Contributing

Issues, bug reports, and pull requests are welcome, and so is "I ran
it on this board and here's what happened", some of the most useful
feedback a hardware project can get.  Development happens in the
[ChuMicro repository](https://github.com/ChuMicro/ChuMicro), whose
contributing guide covers setup and the test workflow.

## Docs

📖 **[Stable docs](https://chumicro.com/ChuMicro/requests/stable/)** · **[Experimental docs](https://chumicro.com/ChuMicro/requests/experimental/)**

## Find this library

- **PyPI:** [chumicro-requests](https://pypi.org/project/chumicro-requests/)
- **Bundle:** [ChuMicro-Bundle](https://github.com/ChuMicro/ChuMicro-Bundle/tree/main/chumicro_requests) (CircuitPython & MicroPython)
- **Experimental bundle:** [ChuMicro-Bundle-Experimental](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental/tree/main/chumicro_requests)
- **Source:** [libraries/requests](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/requests)

## License

[MIT](https://github.com/ChuMicro/ChuMicro/blob/main/LICENSE)
