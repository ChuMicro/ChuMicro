# chumicro-requests

<img src="https://raw.githubusercontent.com/ChuMicro/ChuMicro/main/support/docs/chumicro_tip.png"
align="left" width="64" style="margin-right: 16px; margin-bottom: 8px;">

**Fetch web pages and call web APIs from your board while your main loop keeps running.**

With `adafruit_requests`, `response = requests.get(url)` holds your program on that line until the server answers, so your LED stops blinking and button presses wait for as long as the server takes.  With `chumicro-requests`, `client.get(url)` returns a request handle at once.  Your `while True:` loop calls `client.handle(now_ms)` on each pass.  Each call moves the request one small step and returns, and `request.done` turns `True` when the response is in.

The client speaks HTTP and HTTPS, sends GET, POST, PUT, PATCH, and DELETE with a `json=` shortcut, follows redirects, and decodes chunked responses.  For a body bigger than RAM, such as a firmware image, `stream=True` hands it over a piece at a time through a buffer you own.  The same code runs on CircuitPython, MicroPython, and CPython.

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

The `Runner` loop in the quick example comes from `chumicro-runner`.  Install it the same way.

[Start here](https://chumicro.com/ChuMicro/guides/start-here/) takes a new board from flashing CircuitPython or MicroPython to running your own blink.  [Installing libraries](https://chumicro.com/ChuMicro/guides/install/) covers registering the bundle, the pre-compiled `.mpy` packages, the experimental channel, and why package names use a hyphen on PyPI and an underscore on the board.

## Quick example

This CircuitPython `code.py` fetches a page every 30 seconds.  Put your network name and password in the `connect()` call:

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

On MicroPython, join wifi with `network.WLAN` first, drop `import wifi` and the `connect()` line, and call `connector_factory()` with no `radio`.

`client` is a service, an object a loop drives through two methods.  `check(now_ms)` returns `True` when the client has work to do.  `handle(now_ms)` does one small step of that work.  `request.response` holds what came back: `status_code`, `headers`, `body` as raw bytes, `text` decoded, and `json()`.  A failed request sets `request.error` instead, an `HttpError` that says what went wrong: no answer within 10 seconds, a refused connection, or a reply that is not valid HTTP.

In a program with more going on, hand the loop to [`chumicro-runner`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/runner) and write the fetch as a generator function.  `yield from get(...)` pauses only `fetch_forever` until the response is in, so the fetch reads like `adafruit_requests` code while the runner keeps the rest of the board running:

```python
from chumicro_requests import HttpError
from chumicro_requests.generators import get
from chumicro_runner import Runner
from chumicro_runner.generators import sleep_until
from chumicro_timing import ticks_add, ticks_ms

connector = connector_factory(radio=wifi.radio)


def fetch_forever():
    while True:
        try:
            response = yield from get(connector, "http://example.com/")
            print(response.status_code, len(response.body), "bytes")
        except (HttpError, OSError) as error:
            print("failed:", error)
        yield from sleep_until(ticks_add(ticks_ms(), 30_000))


runner = Runner()
runner.add_generator(fetch_forever())

while True:
    now_ms = runner.tick()  # fetch_forever runs when what it waits for is ready
    runner.wait(now_ms)     # sleep until then
```

[`generator_fetch.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/requests/examples/generator_fetch.py) is the full program.

## What's included

| Symbol | Description |
|---|---|
| `HttpClient` | Makes requests: `get`, `post`, `put`, `patch`, `delete`, or `request(method, url)`.  Call `check(now_ms)` and `handle(now_ms)` from your loop to move the request in flight forward.  `cancel()` abandons it |
| `RequestHandle` | What `get()` and the other verbs return: `.done`, `.response`, `.error`, and `.result`, the response or the error raised.  `.read_body_into(buffer)` reads a `stream=True` body |
| `Response` | `status_code`, `reason`, `headers`, `body` (bytes), and `url`, plus `.text`, `.json()`, and a settable `.encoding` |
| `chumicro_requests.generators` | `get`, `post`, `put`, `patch`, `delete`, and `fetch` for `response = yield from get(...)` code driven by a `Runner`, plus `stream` for reading a large body a piece at a time |
| `chumicro_sockets.sockets_factory.connector_factory(radio=..., ssl_context=...)` | Builds the `transport_factory` that `HttpClient` opens its connections through |
| `CaseInsensitiveDict` | The header dict: `headers["content-type"]` and `headers["Content-Type"]` find the same entry |
| `WhenOversized` | What happens to a body bigger than `max_body_bytes`: dropped quietly, dropped with an `on_oversized` call, or the request fails |
| `HttpError` and subclasses | `HttpTimeoutError`, `HttpProtocolError`, `HttpURLError`, `HttpOversizedError`, and `HttpBusyError`, raised when a second request starts while one is in flight |
| `parse_url`, `parse_charset`, `encode_request`, `ResponseParser` | The HTTP/1.1 pieces `HttpClient` is built from, for code that frames its own requests |
| `chumicro_requests.testing.FakeHttpClient` | A stand-in client for laptop tests: script the responses, no network needed |

## Where this fits

Depends on [`chumicro-sockets`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/sockets) for TCP and TLS connections and [`chumicro-timing`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/timing) for the millisecond clock.  Both install with this library.  Runs as a service on a [`chumicro-runner`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/runner) loop, as the quick example shows.

## Platform support

Works on CPython, MicroPython, and CircuitPython, in pure Python.

On a board, opening the connection holds your loop until it finishes: the DNS lookup, the TLS handshake for an `https://` URL, and on CircuitPython the TCP connect as well.  A slow or unreachable server can hold it for seconds.  Everything after that runs one small step per `handle()` call: sending the request, waiting for the server, and reading the response.

## Examples

| Example | What it shows |
|---|---|
| [`periodic_get.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/requests/examples/periodic_get.py) | Fetches a page every 30 seconds from a plain `while True:` loop that calls `client.check` and `client.handle`, and prints the status and size of each answer.  CircuitPython and MicroPython |
| [`generator_fetch.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/requests/examples/generator_fetch.py) | The same job written as `response = yield from get(...)` in a generator function, run by a `Runner` loop.  CircuitPython and MicroPython |

### Running the examples

Each example joins wifi through `helpers.py`, which sits beside it in `examples/`.  Set `WIFI_SSID` and `WIFI_PASSWORD` at the top of the example.  Copy the example to the board as `code.py` on CircuitPython or `main.py` on MicroPython, together with `helpers.py` and the libraries it imports.  From a clone of the [ChuMicro repository](https://github.com/ChuMicro/ChuMicro), `chumicro-workspace deploy-example requests periodic_get` does the copying and takes the wifi settings from `secrets.toml`.  [Wiring wifi credentials](https://chumicro.com/ChuMicro/guides/wiring-wifi-credentials/) walks through both ways.

## Contributing

Issues, bug reports, and pull requests are welcome, and so is "I ran it on this board and here's what happened", some of the most useful feedback a hardware project can get.  Development happens in the [ChuMicro repository](https://github.com/ChuMicro/ChuMicro), whose contributing guide covers setup and the test workflow.

## Docs

📖 **[Stable docs](https://chumicro.com/ChuMicro/requests/stable/)** · **[Experimental docs](https://chumicro.com/ChuMicro/requests/experimental/)**

## Find this library

- **PyPI:** [chumicro-requests](https://pypi.org/project/chumicro-requests/)
- **Bundle:** [ChuMicro-Bundle](https://github.com/ChuMicro/ChuMicro-Bundle/tree/main/chumicro_requests) (CircuitPython & MicroPython)
- **Experimental bundle:** [ChuMicro-Bundle-Experimental](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental/tree/main/chumicro_requests)
- **Source:** [libraries/requests](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/requests)

## License

[MIT](https://github.com/ChuMicro/ChuMicro/blob/main/LICENSE)
