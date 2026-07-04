"""One-shot fetch generator — happy path + redirect following.

Cross-runtime: runs on CPython (via pytest), MicroPython and CircuitPython
(via chumicro_test_harness).  Drives ``fetch`` directly with
``gen.send`` against a scripted ``FakeSocket`` so assertions hit the
generator's own logic; the runner integration of the deadline-carrying
read-wait is covered in the runner suite.
"""

from _generator_helpers import _drive
from chumicro_requests.generators import (
    delete,
    fetch,
    get,
    patch,
    post,
    put,
)
from chumicro_requests.testing import canned_response, make_factory
from chumicro_sockets.testing import FakeSocket
from chumicro_timing.testing import FakeTicks

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
