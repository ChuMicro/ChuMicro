"""One-shot fetch generator — connect, send, parse, redirect, timeout.

Cross-runtime: runs on CPython (via pytest), MicroPython and CircuitPython
(via chumicro_test_harness).  Drives ``fetch`` directly with
``gen.send`` against a scripted ``FakeSocket`` so assertions hit the
generator's own logic; the runner integration of the deadline-carrying
read-wait is covered in the runner suite.
"""

import errno

from chumicro_requests._wire import (
    HttpOversizedError,
    HttpProtocolError,
    HttpTimeoutError,
)
from chumicro_requests.generators import (
    _ReadDeadlineWait,
    delete,
    fetch,
    get,
    patch,
    post,
    put,
)
from chumicro_requests.testing import canned_response, make_factory
from chumicro_sockets.testing import FakeSocket, FakeSocketConnector
from chumicro_test_harness import raises
from chumicro_timing.testing import FakeTicks


def _drive(gen, ticks, *, advance_ms=1, max_steps=200):
    """Pump *gen* the way the runner would, advancing the fake clock per resume.

    Returns the generator's return value (the ``Response``) on
    ``StopIteration``; advances *ticks* after each yield so deadline
    math progresses.
    """
    value = None
    for _ in range(max_steps):
        try:
            gen.send(value)
        except StopIteration as stop:
            return stop.value
        ticks.advance(advance_ms)
        value = ticks.ticks_ms()
    raise AssertionError("fetch did not complete within max_steps")


# -- happy path ------------------------------------------------------


def test_fetch_returns_response_on_200():
    sock = FakeSocket()
    sock.enqueue_recv(canned_response(status=200, reason="OK", body=b'{"ok": true}'))
    ticks = FakeTicks()
    response = _drive(fetch(make_factory(sock), "GET", "http://example.test/", ticks=ticks), ticks)
    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert response.url == "http://example.test/"
    assert sock.closed is True


def test_get_wrapper_issues_get_request_line_and_host():
    sock = FakeSocket()
    sock.enqueue_recv(canned_response(body=b"hi"))
    ticks = FakeTicks()
    response = _drive(get(make_factory(sock), "http://example.test/path", ticks=ticks), ticks)
    assert response.status_code == 200
    assert response.body == b"hi"
    sent = bytes(sock.sent)
    assert sent.startswith(b"GET /path HTTP/1.1\r\n")
    assert b"Host: example.test\r\n" in sent


def test_post_with_json_sets_content_type():
    sock = FakeSocket()
    sock.enqueue_recv(canned_response(body=b"{}"))
    ticks = FakeTicks()
    response = _drive(post(make_factory(sock), "http://example.test/", json={"a": 1}, ticks=ticks), ticks)
    assert response.status_code == 200
    sent = bytes(sock.sent)
    assert sent.startswith(b"POST / HTTP/1.1\r\n")
    assert b"Content-Type: application/json\r\n" in sent
    assert b"Content-Length: " in sent


def test_verb_wrappers_issue_their_method():
    for verb_function, method in ((put, "PUT"), (patch, "PATCH"), (delete, "DELETE")):
        sock = FakeSocket()
        sock.enqueue_recv(canned_response(body=b"ok"))
        ticks = FakeTicks()
        response = _drive(
            verb_function(make_factory(sock), "http://example.test/resource", ticks=ticks),
            ticks,
        )
        assert response.status_code == 200
        assert bytes(sock.sent).startswith(f"{method} /resource HTTP/1.1\r\n".encode("ascii"))


# -- redirects -------------------------------------------------------


def test_fetch_follows_302_as_get():
    first = FakeSocket()
    first.enqueue_recv(canned_response(status=302, reason="Found", extra_headers=[("Location", "/next")]))
    second = FakeSocket()
    second.enqueue_recv(canned_response(status=200, body=b"final"))
    sockets = [first, second]
    ticks = FakeTicks()
    response = _drive(
        fetch(make_factory(lambda: sockets.pop(0)), "GET", "http://example.test/start", ticks=ticks),
        ticks,
    )
    assert response.status_code == 200
    assert response.body == b"final"
    assert response.url == "http://example.test/next"
    assert bytes(first.sent).startswith(b"GET /start HTTP/1.1\r\n")
    assert bytes(second.sent).startswith(b"GET /next HTTP/1.1\r\n")


def test_fetch_307_preserves_method_and_body():
    first = FakeSocket()
    first.enqueue_recv(canned_response(
        status=307, reason="Temporary Redirect", extra_headers=[("Location", "/again")],
    ))
    second = FakeSocket()
    second.enqueue_recv(canned_response(status=200, body=b"ok"))
    sockets = [first, second]
    ticks = FakeTicks()
    response = _drive(
        post(make_factory(lambda: sockets.pop(0)), "http://example.test/", body=b"payload", ticks=ticks),
        ticks,
    )
    assert response.status_code == 200
    sent_second = bytes(second.sent)
    assert sent_second.startswith(b"POST /again HTTP/1.1\r\n")
    assert b"payload" in sent_second


def test_fetch_returns_redirect_response_when_no_location():
    sock = FakeSocket()
    sock.enqueue_recv(canned_response(status=302, reason="Found"))
    ticks = FakeTicks()
    response = _drive(fetch(make_factory(sock), "GET", "http://example.test/", ticks=ticks), ticks)
    assert response.status_code == 302


def test_fetch_does_not_follow_when_max_redirects_zero():
    sock = FakeSocket()
    sock.enqueue_recv(canned_response(status=302, extra_headers=[("Location", "/next")]))
    ticks = FakeTicks()
    response = _drive(
        fetch(make_factory(sock), "GET", "http://example.test/", ticks=ticks, max_redirects=0),
        ticks,
    )
    assert response.status_code == 302


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


def test_fetch_raises_on_peer_close_before_response():
    sock = FakeSocket()
    sock.simulate_peer_close()  # recv_into returns 0 with no response sent
    ticks = FakeTicks()
    with raises(HttpProtocolError):
        _drive(fetch(make_factory(sock), "GET", "http://example.test/", ticks=ticks), ticks)


def test_fetch_propagates_non_eagain_recv_error():
    class _ResetSock:
        def __init__(self):
            self.sent = bytearray()

        def send(self, data):
            self.sent.extend(bytes(data))
            return len(data)

        def recv_into(self, buffer):  # noqa: ARG002
            raise OSError(errno.ECONNRESET, "connection reset")

        def close(self):
            pass

    def factory(host, port, use_tls):  # noqa: ARG001 - fake ignores args
        return FakeSocketConnector(actions=["dns_ok", "tcp_ok"], socket=_ResetSock())

    ticks = FakeTicks()
    with raises(OSError):
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
    # fires; drive without advancing any fake clock.
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
        value = 0
    assert response is not None
    assert response.status_code == 200


def test_read_deadline_wait_exposes_socket_and_deadline():
    sock = FakeSocket()
    wait = _ReadDeadlineWait(sock, 1234)
    assert wait.io_socket is sock
    assert wait.io_wants_read is True
    assert wait.next_deadline == 1234
