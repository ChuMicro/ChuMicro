---
title: "chumicro-requests: non-blocking HTTP client for CircuitPython and MicroPython"
---

# chumicro-requests

**Fetch web pages and call web APIs from your board while your main loop keeps running.**

With `adafruit_requests`, `response = requests.get(url)` holds your program on that line until the server answers.  With `chumicro-requests`, `client.get(url)` returns a request handle at once, your `while True` loop moves the request forward a small step on each pass, and `request.done` turns `True` when the response is in.  Your LED keeps blinking while the server works on its answer, while the page downloads, and while a stalled server runs out its timeout.  Opening the connection is the exception: [Platform notes](guide.md#platform-notes) lists which connect steps hold the loop on each runtime.  Built on `chumicro-sockets` and `chumicro-timing`.

## Install

```bash
# CircuitPython (after `circup bundle-add ChuMicro/ChuMicro-Bundle`)
circup install chumicro_requests

# MicroPython
mpremote mip install github:ChuMicro/ChuMicro-Bundle/chumicro_requests

# CPython
pip install chumicro-requests
```

No board running yet?  [Start here](https://chumicro.com/ChuMicro/guides/start-here/) goes from a new board to your own code running on it.  [Installing libraries](https://chumicro.com/ChuMicro/guides/install/) covers registering the bundle, the experimental channel, and the pre-compiled `.mpy` packages.

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

On MicroPython, join wifi with `network.WLAN` as usual and call `connector_factory()` with no `radio`.  `request.response` carries `status_code`, `headers`, `body`, `text`, and `json()`; a failed request sets `request.error` instead.

## The same fetch, written top to bottom

A generator function lets the fetch read like `adafruit_requests` code.  `yield from get(...)` pauses only `fetch_forever` until the response is in, and the `Runner` loop at the bottom keeps the rest of the board running meanwhile:

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
    runner.wait(now_ms)     # the CPU rests until then
```

## Documentation

- [User Guide](guide.md): the request loop, reading responses, generator functions, running beside other services, sending data, timeouts and errors, redirects, streaming large bodies, HTTPS, bringing your own transport
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
