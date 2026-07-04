"""requests client: POST, default-header merge."""

from chumicro_requests import (
    HttpBusyError,
    HttpURLError,
)
from chumicro_requests.testing import (
    canned_response,
    drive_until_done,
    make_client,
)
from chumicro_runner import IO_READ
from chumicro_sockets.testing import FakeSocket
from chumicro_test_harness.assertions import raises


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
        # No body: encode_request omits Content-Length.
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


class TestRequestBodyRam:
    """Body bytes aren't held in duplicate longer than a hop needs them."""

    def test_tx_buffer_released_once_send_completes(self):
        # A recv with no queued response stalls the request in RECEIVING;
        # the transmit buffer must be empty by then, not still pinning a
        # second copy of the request bytes through the receive phase.
        socket = FakeSocket()
        client, ticks, _ = make_client(socket_or_factory=socket)
        client.post("http://example.test/api", body=b"payload-body")
        for _ in range(10):
            client.handle(ticks.ticks_ms())
            ticks.advance(1)
        assert client.io_interest(ticks.ticks_ms()) == IO_READ  # in RECEIVING
        assert client._tx_buffer == b""  # noqa: SLF001 - released at send end
        assert client._tx_offset == 0  # noqa: SLF001

    def test_original_body_not_captured_when_redirects_disabled(self):
        # max_redirects=0 makes 307/308 replay impossible, so the replay
        # copy of the body must not be retained.
        socket = FakeSocket()
        client, _ticks, _ = make_client(socket_or_factory=socket)
        client.post(
            "http://example.test/api", body=b"payload-body", max_redirects=0,
        )
        assert client._original_body is None  # noqa: SLF001

    def test_original_body_captured_when_redirects_allowed(self):
        socket = FakeSocket()
        client, _ticks, _ = make_client(socket_or_factory=socket)
        client.post(
            "http://example.test/api", body=b"payload-body", max_redirects=3,
        )
        assert client._original_body == b"payload-body"  # noqa: SLF001


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
