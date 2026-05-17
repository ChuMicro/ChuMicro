"""requests client: POST, default-header merge."""

from chumicro_requests import (
    HttpBusyError,
    HttpClient,
    HttpURLError,
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


class TestHttpClientPost:
    """POST + body + json= helper."""

    def test_post_with_bytes_body(self):
        socket = FakeSocket()
        socket.enqueue_recv(canned_response(body=b"ok"))
        client, ticks, _ = make_client(socket_or_factory=socket)

        handle = client.post("http://example.test/api", body=b"payload-bytes")
        drive_until_done(client, handle, ticks)
        assert handle.result.body == b"ok"
        assert socket.sent.startswith(b"POST /api HTTP/1.1\r\n")
        assert b"Content-Length: 13\r\n" in socket.sent
        assert socket.sent.endswith(b"\r\n\r\npayload-bytes")

    def test_post_with_str_body_encodes_utf8(self):
        socket = FakeSocket()
        socket.enqueue_recv(canned_response(body=b""))
        client, ticks, _ = make_client(socket_or_factory=socket)

        handle = client.post("http://example.test/api", body="café")
        drive_until_done(client, handle, ticks)
        # "café".encode("utf-8") == b"caf\xc3\xa9" (5 bytes)
        assert b"Content-Length: 5\r\n" in socket.sent
        assert socket.sent.endswith(b"\r\n\r\ncaf\xc3\xa9")

    def test_post_with_json_serializes_and_sets_content_type(self):
        socket = FakeSocket()
        socket.enqueue_recv(canned_response(body=b'{"received":true}'))
        client, ticks, _ = make_client(socket_or_factory=socket)

        handle = client.post(
            "http://example.test/api",
            json={"sensor_id": 42, "temp_f": 72},
        )
        drive_until_done(client, handle, ticks)
        assert handle.result.status_code == 200
        # Body is JSON-encoded
        assert b'"sensor_id": 42' in socket.sent or b'"sensor_id":42' in socket.sent
        assert b"Content-Type: application/json\r\n" in socket.sent
        assert b"Content-Length:" in socket.sent

    def test_post_caller_content_type_overrides_json_default(self):
        socket = FakeSocket()
        socket.enqueue_recv(canned_response(body=b""))
        client, ticks, _ = make_client(socket_or_factory=socket)

        handle = client.post(
            "http://example.test/api",
            json={"k": "v"},
            headers={"Content-Type": "application/json+custom"},
        )
        drive_until_done(client, handle, ticks)
        assert b"Content-Type: application/json+custom\r\n" in socket.sent
        # The default application/json should NOT also be present
        assert b"Content-Type: application/json\r\n" not in socket.sent

    def test_post_body_and_json_mutually_exclusive(self):
        client, _ticks, _ = make_client()
        with raises(ValueError, match="not both"):
            client.post("http://example.test/", body=b"x", json={"k": "v"})

    def test_post_rejects_non_bytes_non_str_body(self):
        client, _ticks, _ = make_client()
        with raises(TypeError, match="bytes / bytearray / str"):
            client.post("http://example.test/", body=42)

    def test_post_with_bytearray_body(self):
        socket = FakeSocket()
        socket.enqueue_recv(canned_response(body=b""))
        client, ticks, _ = make_client(socket_or_factory=socket)

        handle = client.post("http://example.test/", body=bytearray(b"ba"))
        drive_until_done(client, handle, ticks)
        assert socket.sent.endswith(b"\r\n\r\nba")

    def test_post_no_body(self):
        """POST with neither body= nor json= — empty body, no Content-Length."""
        socket = FakeSocket()
        socket.enqueue_recv(canned_response(body=b""))
        client, ticks, _ = make_client(socket_or_factory=socket)

        handle = client.post("http://example.test/")
        drive_until_done(client, handle, ticks)
        # No body → no Content-Length added by encode_request
        assert b"Content-Length:" not in socket.sent
        assert socket.sent.startswith(b"POST / HTTP/1.1\r\n")

    def test_put_request(self):
        socket = FakeSocket()
        socket.enqueue_recv(canned_response(body=b""))
        client, ticks, _ = make_client(socket_or_factory=socket)

        handle = client.put("http://example.test/widgets/42", body=b"updated")
        drive_until_done(client, handle, ticks)
        assert socket.sent.startswith(b"PUT /widgets/42 HTTP/1.1\r\n")
        assert socket.sent.endswith(b"\r\n\r\nupdated")

    def test_patch_request_with_json(self):
        socket = FakeSocket()
        socket.enqueue_recv(canned_response(body=b""))
        client, ticks, _ = make_client(socket_or_factory=socket)

        handle = client.patch(
            "http://example.test/widgets/42",
            json={"name": "renamed"},
        )
        drive_until_done(client, handle, ticks)
        assert socket.sent.startswith(b"PATCH /widgets/42 HTTP/1.1\r\n")
        assert b"Content-Type: application/json\r\n" in socket.sent

    def test_delete_request(self):
        socket = FakeSocket()
        socket.enqueue_recv(canned_response(body=b""))
        client, ticks, _ = make_client(socket_or_factory=socket)

        handle = client.delete("http://example.test/widgets/42")
        drive_until_done(client, handle, ticks)
        assert socket.sent.startswith(b"DELETE /widgets/42 HTTP/1.1\r\n")
        # DELETE never has a body in v1.
        assert socket.sent.endswith(b"\r\n\r\n")
        assert b"Content-Length:" not in socket.sent

    def test_post_busy_error_when_in_flight(self):
        socket = FakeSocket()
        client, _ticks, _ = make_client(socket_or_factory=socket)
        client.post("http://example.test/one", body=b"first")
        with raises(HttpBusyError):
            client.post("http://example.test/two", body=b"second")

    def test_post_url_error_propagates(self):
        client, _ticks, _ = make_client()
        with raises(HttpURLError):
            client.post("ftp://bad/", body=b"x")


class TestMergeDefaultHeader:
    """Helper: caller-supplied headers override the default."""

    def test_dict_input_overrides_default(self):
        from chumicro_requests.client import _merge_default_header

        merged = _merge_default_header(
            {"Content-Type": "text/plain"},
            "Content-Type", "application/json",
        )
        assert merged["Content-Type"] == "text/plain"

    def test_iterable_input(self):
        from chumicro_requests.client import _merge_default_header

        merged = _merge_default_header(
            [("X-Custom", "v")],
            "Content-Type", "application/json",
        )
        assert merged["x-custom"] == "v"
        assert merged["Content-Type"] == "application/json"

    def test_caseinsensitive_dict_input(self):
        from chumicro_requests._wire import CaseInsensitiveDict
        from chumicro_requests.client import _merge_default_header

        original = CaseInsensitiveDict()
        original["X-Custom"] = "v"
        merged = _merge_default_header(
            original, "Content-Type", "application/json",
        )
        assert merged["X-Custom"] == "v"

    def test_none_input_keeps_default(self):
        from chumicro_requests.client import _merge_default_header

        merged = _merge_default_header(None, "Content-Type", "application/json")
        assert merged["Content-Type"] == "application/json"
