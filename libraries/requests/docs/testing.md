# Testing Helpers

`chumicro_requests.testing` stands in for the web server at the other end of a request.  `FakeHttpClient` replaces a whole `HttpClient` and answers each request from a list of scripted replies.  `make_client` and its helpers run the real `HttpClient` against a fake socket, for a test of the HTTP bytes themselves.  `pip install chumicro-requests pytest` installs everything the tests on this page import, `chumicro-sockets` and `chumicro-timing` included.  Project deploys and the board bundles leave the module out.

## The smallest test

A program that takes its `HttpClient` as an argument gets a `FakeHttpClient` in a test.  Save this as `test_weather.py` and run `pytest test_weather.py`:

```python
from chumicro_requests.testing import FakeHttpClient


class WeatherFetcher:
    def __init__(self, http_client):
        self.http_client = http_client
        self.request = None
        self.temperature = None

    def tick(self, now_ms):
        if self.request is None:
            self.request = self.http_client.get("http://api.example.test/weather")
        if self.http_client.check(now_ms):
            self.http_client.handle(now_ms)
        if self.request.done:
            self.temperature = self.request.result.json()["temp_f"]
            self.request = None


def test_fetcher_reads_the_temperature():
    fake = FakeHttpClient()
    fake.enqueue_response(status=200, body=b'{"temp_f": 72}')

    weather = WeatherFetcher(fake)
    weather.tick(0)

    assert weather.temperature == 72
    assert fake.calls[0].url == "http://api.example.test/weather"
```

On the board, `WeatherFetcher` gets a real `HttpClient`.  In the test, `get()` takes the first scripted reply and the next `handle()` finishes the request with it.

## `FakeHttpClient`

`FakeHttpClient` answers the same `get`, `post`, `put`, `patch`, `delete`, `request`, `check`, `handle`, `cancel`, and `busy` calls as `HttpClient`.

| Call or attribute | What it does |
|---|---|
| `enqueue_response(*, status=200, reason="OK", http_version="HTTP/1.1", headers=None, body=b"", oversized_dropped=False)` | Scripts the next request to succeed with this reply.  `headers` takes a `dict` or `(name, value)` pairs. |
| `enqueue_error(error)` | Scripts the next request to fail with `error`, any `HttpError` such as `HttpTimeoutError`. |
| `calls` | One record per request, in order, with its `method`, `url`, `headers`, `body`, `json`, `timeout_ms`, `max_redirects`, and `stream`. |
| `cancel()` | Fails the request in flight with an `HttpError` and calls its `on_done`, as `HttpClient.cancel()` does. |

A request with no scripted reply left raises `HttpError`.  A second request while one is in flight raises `HttpBusyError`, as the real client does.

`enqueue_error` scripts a failure, so a test covers the error path without waiting for a real timeout:

```python
from chumicro_requests import HttpTimeoutError
from chumicro_requests.testing import FakeHttpClient


def test_a_scripted_timeout_fails_the_request():
    fake = FakeHttpClient()
    fake.enqueue_error(HttpTimeoutError("simulated timeout"))

    request = fake.get("http://api.example.test/weather")
    fake.handle(0)

    assert request.done
    assert isinstance(request.error, HttpTimeoutError)
```

A `stream=True` request finishes in one `handle()` call.  The scripted body then drains through `read_body_into`, which returns `0` at the end:

```python
from chumicro_requests.testing import FakeHttpClient


def test_a_streamed_body_arrives_in_pieces():
    fake = FakeHttpClient()
    fake.enqueue_response(status=200, body=b"blob-bytes")

    request = fake.get("http://example.test/blob", stream=True)
    fake.handle(0)

    buffer = bytearray(4)
    assert request.read_body_into(buffer) == 4
    assert bytes(buffer) == b"blob"
    assert request.result.streamed is True
    assert fake.calls[0].stream is True
```

## `make_client` and the socket helpers

`make_client` and its helpers run the real `HttpClient` on a `FakeSocket` from `chumicro_sockets.testing`, so a test checks the bytes that cross the wire.

| Helper | What it does |
|---|---|
| `make_client(*, socket_or_factory=None, **kwargs)` | Builds an `HttpClient` on a `FakeTicks` clock and a `FakeSocket`, and returns `(client, ticks, socket)`.  Keywords pass to `HttpClient`. |
| `canned_response(*, status=200, reason="OK", body=b"", extra_headers=())` | Returns a raw HTTP/1.1 reply with `Content-Length` and `Content-Type: text/plain`, ready for `socket.enqueue_recv`. |
| `drive_until_done(client, handle, ticks, *, max_ticks=200, advance_ms=1)` | Ticks the client until `handle.done`, and raises `AssertionError` after `max_ticks` passes. |
| `make_factory(socket_or_factory)` | Returns a `transport_factory` that connects at once and hands the client that socket. |

```python
from chumicro_requests.testing import canned_response, drive_until_done, make_client


def test_the_real_client_reads_a_canned_reply():
    client, ticks, socket = make_client()
    socket.enqueue_recv(canned_response(status=200, body=b"hello"))

    request = client.get("http://example.test/")
    drive_until_done(client, request, ticks)

    assert request.result.status_code == 200
    assert request.result.text == "hello"
    assert socket.sent.startswith(b"GET / HTTP/1.1\r\n")
```

## API reference

::: chumicro_requests.testing

---

<div class="chumicro-footer" markdown>

[← Home](index.md)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/requests) · \
[PyPI](https://pypi.org/project/chumicro-requests/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
