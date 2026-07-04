"""One-shot fetch generator — error paths + wait-token shape.

Cross-runtime: runs on CPython (via pytest), MicroPython and CircuitPython
(via chumicro_test_harness).  Drives ``fetch`` directly with
``gen.send`` against a scripted ``FakeSocket`` so assertions hit the
generator's own logic; the runner integration of the client-as-wait-token
is covered in the runner suite.
"""

import errno

from _generator_helpers import _drive
from chumicro_requests._wire import (
    HttpError,
    HttpOversizedError,
    HttpProtocolError,
    HttpTimeoutError,
)
from chumicro_requests.generators import fetch
from chumicro_requests.testing import canned_response, make_factory
from chumicro_runner import IO_READ
from chumicro_sockets.testing import FakeSocket, FakeSocketConnector
from chumicro_test_harness import raises
from chumicro_timing.testing import FakeTicks

# -- error paths -----------------------------------------------------


def test_fetch_raises_on_oversized_body():
    sock = FakeSocket()
    sock.enqueue_recv(canned_response(body=b"x" * 100))
    ticks = FakeTicks()
    gen = fetch(make_factory(sock), "GET", "http://example.test/", ticks=ticks, max_body_bytes=10)
    with raises(HttpOversizedError):
        _drive(gen, ticks)


def test_fetch_times_out_on_silent_peer():
    sock = FakeSocket()  # nothing enqueued -> recv_into always EAGAIN
    ticks = FakeTicks()
    with raises(HttpTimeoutError):
        _drive(
            fetch(make_factory(sock), "GET", "http://example.test/", ticks=ticks, timeout_ms=5),
            ticks,
            advance_ms=1,
            max_steps=100,
        )


def test_fetch_times_out_when_connect_never_completes():
    # Connector stalls at awaiting_tcp (dns_ok only, no tcp_ok), so the
    # connect phase never reaches ready; the client's per-request
    # deadline trips and fetch surfaces it as HttpTimeoutError.
    def factory(host, port, use_tls):  # noqa: ARG001 - fake ignores args
        return FakeSocketConnector(actions=["dns_ok"])

    ticks = FakeTicks()
    with raises(HttpTimeoutError):
        _drive(
            fetch(factory, "GET", "http://example.test/", ticks=ticks, timeout_ms=5),
            ticks,
            advance_ms=2,
            max_steps=100,
        )


def test_fetch_raises_on_peer_close_before_response():
    sock = FakeSocket()
    sock.simulate_peer_close()  # recv_into returns 0 with no response sent
    ticks = FakeTicks()
    with raises(HttpProtocolError):
        _drive(fetch(make_factory(sock), "GET", "http://example.test/", ticks=ticks), ticks)


def test_fetch_wraps_non_eagain_recv_error_in_http_error():
    """A non-retryable socket error (ECONNRESET) fails the request with
    HttpError — the documented failure type — and the message names the
    underlying OSError so the cause stays visible."""

    class _ResetSock:
        def __init__(self):
            self.sent = bytearray()

        def send(self, data):
            self.sent.extend(bytes(data))
            return len(data)

        def recv_into(self, buffer, nbytes=0):  # noqa: ARG002
            raise OSError(errno.ECONNRESET, "connection reset")

        def close(self):
            pass

    def factory(host, port, use_tls):  # noqa: ARG001 - fake ignores args
        return FakeSocketConnector(actions=["dns_ok", "tcp_ok"], socket=_ResetSock())

    ticks = FakeTicks()
    with raises(HttpError):
        _drive(fetch(factory, "GET", "http://example.test/", ticks=ticks), ticks)


def test_fetch_rejects_body_and_json_together():
    sock = FakeSocket()
    gen = fetch(
        make_factory(sock), "POST", "http://example.test/",
        body=b"x", json={"a": 1}, ticks=FakeTicks(),
    )
    with raises(ValueError):
        gen.send(None)


# -- wait shape ------------------------------------------------------


def test_fetch_uses_default_ticks_when_none():
    # No ticks= injected: fetch falls back to chumicro_timing.ticks (the
    # on-device path).  Data is immediate so the real-clock deadline never
    # fires; drive with real tick readings so the client's deadline math
    # sees a coherent clock.
    from chumicro_timing import ticks as real_ticks

    sock = FakeSocket()
    sock.enqueue_recv(canned_response(body=b"ok"))
    gen = fetch(make_factory(sock), "GET", "http://example.test/")
    response = None
    value = None
    for _ in range(50):
        try:
            gen.send(value)
        except StopIteration as stop:
            response = stop.value
            break
        value = real_ticks.ticks_ms()
    assert response is not None
    assert response.status_code == 200


def test_fetch_yields_the_client_as_its_wait_token():
    """fetch parks the scheduler on the request's own HttpClient: the
    yielded wait exposes io_socket / io_interest / next_deadline, and
    once the connector promotes, it reports read interest on the
    FakeSocket with the absolute request deadline."""
    sock = FakeSocket()  # nothing enqueued -> stalls in RECEIVING
    ticks = FakeTicks()
    gen = fetch(
        make_factory(sock), "GET", "http://example.test/",
        ticks=ticks, timeout_ms=500,
    )
    wait = gen.send(None)
    # Drive until the request is mid-receive; the same client token is
    # re-yielded every resume.
    for _ in range(5):
        wait = gen.send(ticks.ticks_ms())
    assert wait.io_socket is sock
    assert wait.io_interest(ticks.ticks_ms()) == IO_READ
    assert wait.next_deadline(ticks.ticks_ms()) == 500
    gen.close()
