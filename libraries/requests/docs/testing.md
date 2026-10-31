# Testing Helpers

`chumicro_requests.testing` holds fakes for testing your own code on a laptop, with no board and no network.  Import them from the installed package, the same way this library's own tests do.  The module never ships to a board: deploys and the CircuitPython and MicroPython bundles leave it out.

## `FakeHttpClient`

An in-memory stand-in for `HttpClient`.  It answers the same `get` / `post` / `check` / `handle` / `busy` / `cancel` calls the real client answers.  You script each answer up front with `enqueue_response()` (success) or `enqueue_error()` (failure).  Each request pops the next scripted answer, and the next `handle()` call finishes the `RequestHandle` with it.

Say your program has a class that fetches a temperature through an `HttpClient` passed in when you build it:

```python
class WeatherFetcher:
    def __init__(self, http_client):
        self.http_client = http_client
        self.request = None
        self.last_temperature = None
        self.last_error_message = None

    def tick(self, now_ms):
        if self.request is None:
            self.request = self.http_client.get("http://api.example.test/weather")
        if self.http_client.check(now_ms):
            self.http_client.handle(now_ms)
        if self.request.done:
            if self.request.error is not None:
                self.last_error_message = str(self.request.error)
            else:
                self.last_temperature = self.request.response.json()["temp_f"]
            self.request = None
```

On the board you pass it a real `HttpClient`.  In a test you pass a `FakeHttpClient` with the answer already scripted:

```python
from chumicro_requests.testing import FakeHttpClient

fake = FakeHttpClient()
fake.enqueue_response(status=200, body=b'{"temp_f": 72}')

weather = WeatherFetcher(http_client=fake)
weather.tick(now_ms=0)        # get() takes the scripted answer, handle() finishes the request

assert weather.last_temperature == 72
assert fake.calls[0].url == "http://api.example.test/weather"
```

`fake.calls` records every request in order, with its `method`, `url`, `headers`, `body`, `json`, `timeout_ms`, `max_redirects`, and `stream`.

## Scripting a failure

`enqueue_error()` takes any `HttpError`, so you can check how your code handles a timeout without waiting for one:

```python
from chumicro_requests import HttpTimeoutError
from chumicro_requests.testing import FakeHttpClient

fake = FakeHttpClient()
fake.enqueue_error(HttpTimeoutError("simulated timeout"))

weather = WeatherFetcher(http_client=fake)
weather.tick(now_ms=0)

assert weather.last_error_message == "simulated timeout"
```

## Streamed requests

A `stream=True` request against the fake finishes in one `handle()` call, and the scripted body then drains through `read_body_into`: bytes first, then `0` for end of body.

```python
fake = FakeHttpClient()
fake.enqueue_response(status=200, body=b"blob-bytes")

handle = fake.get("http://example.test/blob", stream=True)
fake.handle(now_ms=0)

buffer = bytearray(4)
assert handle.read_body_into(buffer) == 4      # b"blob"
assert handle.result.streamed is True
assert fake.calls[0].stream is True
```

`fake.cancel()` behaves like `HttpClient.cancel()`: the request in flight finishes with an `HttpError`, and its `on_done` callback fires.

## API Reference

::: chumicro_requests.testing

---

<div class="chumicro-footer" markdown>

[← Home](index.md)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/requests) · \
[PyPI](https://pypi.org/project/chumicro-requests/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
