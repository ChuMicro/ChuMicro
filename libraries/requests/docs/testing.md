# Testing Helpers

Host-only fakes for testing code that depends on `chumicro-requests`.  `chumicro_requests.testing` declares itself test support, so the deploy walker and the bundle builder drop it and it never lands on a microcontroller.

## `FakeHttpClient`

In-memory `HttpClient` stand-in.  It answers the same `get` / `check` / `handle` / `busy` / `on_oversized` calls the real client answers, and tests script responses with `enqueue_response()` (success) or `enqueue_error()` (failure).  Each `get()` pops one scripted entry, and the next `handle()` tick completes the `RequestHandle`.

```python
from chumicro_requests.testing import FakeHttpClient

fake = FakeHttpClient()
fake.enqueue_response(status=200, body=b'{"temp_f": 72}')

weather = WeatherFetcher(http_client=fake)
weather.tick(now_ms=0)        # internally calls fake.get(...)
weather.tick(now_ms=10)       # one handle() tick completes the request

assert weather.last_temperature == 72
assert fake.calls[0].url == "http://api.example.test/weather"
```

## Streamed requests

A `stream=True` request against the fake compresses the real client's contract into one tick: `handle()` completes the request, and the scripted body drains through `read_body_into`, bytes first, then `0` for end of body.

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

`fake.cancel()` mirrors `HttpClient.cancel()`: the in-flight handle finishes with an `HttpError` and its `on_done` callback fires.

## `enqueue_error` example

```python
from chumicro_requests import HttpTimeoutError
from chumicro_requests.testing import FakeHttpClient

fake = FakeHttpClient()
fake.enqueue_error(HttpTimeoutError("simulated timeout"))

weather = WeatherFetcher(http_client=fake)
weather.tick(now_ms=0)
weather.tick(now_ms=10)
assert weather.last_error_message == "simulated timeout"
```

## Using these fakes in your own tests

Your test suite imports the fake straight from the installed package, the same way this library's own tests do:

```python
from chumicro_requests.testing import FakeHttpClient
```

Project convention: libraries that expose injectable services ship their own test fakes alongside the production code.

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
