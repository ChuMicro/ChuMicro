"""requests client: response decode, GET, runner contract. Sibling:
other test_client_*.py; wire-level in test_wire_*.py."""

from chumicro_requests import (
    CaseInsensitiveDict,
    HttpClient,
    Response,
)
from chumicro_sockets.testing import FakeSocket
from chumicro_test_harness.assertions import raises
from chumicro_timing.testing import FakeTicks


def make_factory(socket_or_factory):
    """Return a connection_factory that hands out *socket_or_factory*.

    *socket_or_factory* can be either a single :class:`FakeSocket`
    (returned every call) or a zero-arg callable that builds a fresh
    one on demand.
    """
    def factory(host, port, use_tls):  # noqa: ARG001 — fake ignores args
        if callable(socket_or_factory):
            return socket_or_factory()
        return socket_or_factory

    return factory

def canned_response(*, status=200, reason="OK", body=b"", extra_headers=()):
    """Build an HTTP/1.1 response byte-string with Content-Length."""
    lines = [f"HTTP/1.1 {status} {reason}\r\n".encode("ascii")]
    lines.append(f"Content-Length: {len(body)}\r\n".encode("ascii"))
    lines.append(b"Content-Type: text/plain\r\n")
    for name, value in extra_headers:
        lines.append(f"{name}: {value}\r\n".encode("ascii"))
    lines.append(b"\r\n")
    lines.append(body)
    return b"".join(lines)

def drive_until_done(client, handle, ticks, *, max_ticks=200, advance_ms=1):
    """Run handle/check until done; safety-cap at *max_ticks* iterations."""
    for _ in range(max_ticks):
        if handle.done:
            return
        if client.check(ticks.ticks_ms()):
            client.handle(ticks.ticks_ms())
        ticks.advance(advance_ms)
    raise AssertionError(f"handle never completed within {max_ticks} ticks")

def make_client(*, socket_or_factory=None, **kwargs):
    """Construct an HttpClient wired to FakeTicks + a FakeSocket factory."""
    ticks = FakeTicks()
    socket = socket_or_factory if socket_or_factory is not None else FakeSocket()
    client = HttpClient(
        connection_factory=make_factory(socket),
        ticks=ticks,
        **kwargs,
    )
    return client, ticks, socket


class TestResponseDecode:
    """``.encoding`` / ``.text`` / ``.json()`` cover decode + JSON parse."""

    def _make(self, *, body, content_type=None, encoding=None):
        headers = CaseInsensitiveDict()
        if content_type is not None:
            headers["Content-Type"] = content_type
        return Response(
            status_code=200,
            reason="OK",
            http_version="HTTP/1.1",
            headers=headers,
            body=body,
            url="http://example.test/",
            encoding=encoding,
        )

    def test_text_default_utf8(self):
        response = self._make(body="café".encode())
        assert response.encoding == "utf-8"
        assert response.text == "café"

    def test_text_uses_content_type_charset(self):
        response = self._make(
            body="café".encode("latin-1"),
            content_type="text/plain; charset=latin-1",
        )
        assert response.encoding == "latin-1"
        assert response.text == "café"

    def test_encoding_override_via_constructor(self):
        response = self._make(
            body="café".encode("latin-1"),
            content_type="text/plain; charset=utf-8",  # server lies
            encoding="latin-1",
        )
        assert response.encoding == "latin-1"
        assert response.text == "café"

    def test_encoding_setter_overrides(self):
        response = self._make(body="café".encode("latin-1"))
        response.encoding = "latin-1"
        assert response.encoding == "latin-1"
        assert response.text == "café"

    def test_json_decode(self):
        response = self._make(
            body=b'{"temp_f": 72, "ok": true}',
            content_type="application/json",
        )
        result = response.json()
        assert result == {"temp_f": 72, "ok": True}

    def test_json_invalid_raises(self):
        response = self._make(body=b"not-json", content_type="application/json")
        with raises(ValueError):
            response.json()

    def test_text_decode_error_propagates(self):
        # Latin-1-only byte that's invalid UTF-8.
        response = self._make(body=b"\xff", content_type="text/plain; charset=utf-8")
        with raises(UnicodeError):
            _ = response.text


class TestHttpClientGet:
    """End-to-end GET against FakeSocket — slice 3a happy path + structure."""

    def test_simple_get_returns_response(self):
        socket = FakeSocket()
        socket.enqueue_recv(canned_response(body=b"hello"))
        client, ticks, _ = make_client(socket_or_factory=socket)

        handle = client.get("http://example.test/")
        assert not handle.done
        drive_until_done(client, handle, ticks)

        response = handle.result
        assert isinstance(response, Response)
        assert response.status_code == 200
        assert response.reason == "OK"
        assert response.http_version == "HTTP/1.1"
        assert response.body == b"hello"
        assert response.headers["content-type"] == "text/plain"
        assert response.url == "http://example.test/"

    def test_request_bytes_sent_to_socket(self):
        socket = FakeSocket()
        socket.enqueue_recv(canned_response(body=b""))
        client, ticks, _ = make_client(socket_or_factory=socket)

        handle = client.get("http://example.test/api/widgets")
        drive_until_done(client, handle, ticks)

        assert socket.sent.startswith(b"GET /api/widgets HTTP/1.1\r\n")
        assert b"Host: example.test\r\n" in socket.sent
        assert socket.sent.endswith(b"\r\n\r\n")

    def test_non_default_port_in_host_header(self):
        socket = FakeSocket()
        socket.enqueue_recv(canned_response(body=b""))
        client, ticks, _ = make_client(socket_or_factory=socket)

        handle = client.get("http://example.test:8080/")
        drive_until_done(client, handle, ticks)

        assert b"Host: example.test:8080\r\n" in socket.sent

    def test_caller_headers_passed_through(self):
        socket = FakeSocket()
        socket.enqueue_recv(canned_response(body=b""))
        client, ticks, _ = make_client(socket_or_factory=socket)

        handle = client.get(
            "http://example.test/",
            headers={"Authorization": "Bearer secret"},
        )
        drive_until_done(client, handle, ticks)

        assert b"Authorization: Bearer secret\r\n" in socket.sent

    def test_user_agent_override_at_construction(self):
        socket = FakeSocket()
        socket.enqueue_recv(canned_response(body=b""))
        client, ticks, _ = make_client(
            socket_or_factory=socket, user_agent="custom-agent/9",
        )

        handle = client.get("http://example.test/")
        drive_until_done(client, handle, ticks)

        assert b"User-Agent: custom-agent/9\r\n" in socket.sent

    def test_https_url_dispatches_with_use_tls_true(self):
        """``https://`` URLs route to the connection_factory with
        ``use_tls=True`` and skip the port in the Host header when
        it equals 443 (the scheme default)."""
        socket = FakeSocket()
        socket.enqueue_recv(canned_response(body=b"secured"))
        captured = []

        def factory(host, port, use_tls):
            captured.append((host, port, use_tls))
            return socket

        ticks = FakeTicks()
        client = HttpClient(
            connection_factory=factory,
            ticks=ticks,
        )
        handle = client.get("https://example.test/secret")
        drive_until_done(client, handle, ticks)
        assert handle.result.body == b"secured"
        assert captured == [("example.test", 443, True)]
        # Host header omits the default 443 port.
        assert b"Host: example.test\r\n" in socket.sent

    def test_https_explicit_port_kept_in_host_header(self):
        socket = FakeSocket()
        socket.enqueue_recv(canned_response(body=b""))
        captured = []

        def factory(host, port, use_tls):
            captured.append((host, port, use_tls))
            return socket

        ticks = FakeTicks()
        client = HttpClient(
            connection_factory=factory,
            ticks=ticks,
        )
        handle = client.get("https://example.test:8443/")
        drive_until_done(client, handle, ticks)
        assert captured == [("example.test", 8443, True)]
        assert b"Host: example.test:8443\r\n" in socket.sent

    def test_socket_closed_after_completion(self):
        socket = FakeSocket()
        socket.enqueue_recv(canned_response(body=b"x"))
        client, ticks, _ = make_client(socket_or_factory=socket)
        handle = client.get("http://example.test/")
        drive_until_done(client, handle, ticks)
        assert socket.closed is True
        assert client.busy is False


class TestHttpClientRunnerContract:
    """``check`` and ``handle`` satisfy the runner contract."""

    def test_check_false_when_idle(self):
        client, ticks, _ = make_client()
        assert client.check(ticks.ticks_ms()) is False

    def test_check_true_while_in_flight(self):
        socket = FakeSocket()
        # Don't queue a response — leave the request stalled in receive.
        client, ticks, _ = make_client(socket_or_factory=socket)
        client.get("http://example.test/")
        assert client.check(ticks.ticks_ms()) is True

    def test_handle_when_idle_is_noop(self):
        client, ticks, _ = make_client()
        client.handle(ticks.ticks_ms())  # safe; nothing to do
        assert client.busy is False

    def test_busy_property_tracks_in_flight(self):
        socket = FakeSocket()
        client, ticks, _ = make_client(socket_or_factory=socket)
        assert client.busy is False
        client.get("http://example.test/")
        assert client.busy is True
