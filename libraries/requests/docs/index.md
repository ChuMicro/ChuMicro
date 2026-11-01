---
title: "chumicro-requests: non-blocking HTTP client for CircuitPython and MicroPython"
---

# chumicro-requests

**Fetch web pages and call web APIs from your board while your main loop keeps running.**

With `adafruit_requests`, `response = requests.get(url)` holds your program on that line until the server answers, so your LED stops blinking and button presses wait for as long as the server takes.  With `chumicro-requests`, `client.get(url)` returns a request handle at once.  Your `while True:` loop calls `client.handle(now_ms)` on each pass.  Each call moves the request one small step and returns, and `request.done` turns `True` when the response is in.

The client speaks HTTP and HTTPS, sends GET, POST, PUT, PATCH, and DELETE with a `json=` shortcut, follows redirects, and decodes chunked responses.  For a body bigger than RAM, such as a firmware image, `stream=True` hands it over a piece at a time through a buffer you own.  The same code runs on CircuitPython, MicroPython, and CPython.

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

In a program with more going on, hand the loop to [`chumicro-runner`](https://chumicro.com/ChuMicro/runner/stable/) and write the fetch as a generator function.  `yield from get(...)` pauses only `fetch_forever` until the response is in, so the fetch reads like `adafruit_requests` code while the runner keeps the rest of the board running:

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

[`generator_fetch.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/requests/examples/generator_fetch.py) is the full program.  Opening a connection holds the loop on a board.  [Platform notes](guide.md#platform-notes) lists which steps hold it on each runtime.

## Documentation

- [User Guide](guide.md): the request loop, reading responses, writing the fetch as a generator, the runner pattern, sending data, timeouts and errors, redirects, streaming large bodies, HTTPS, and bringing your own transport
- [API Reference](api.md): `HttpClient`, `RequestHandle`, and `Response`, plus the `yield from` generator helpers
- [Testing Helpers](testing.md): `FakeHttpClient`, a scripted stand-in client for your tests

---

<div class="chumicro-footer" markdown>

[← All ChuMicro Libraries](../../)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/requests) · \
[PyPI](https://pypi.org/project/chumicro-requests/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
