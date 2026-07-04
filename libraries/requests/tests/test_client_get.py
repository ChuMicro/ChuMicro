"""requests client: end-to-end GET against FakeSocket + runner contract."""

from chumicro_requests import (
    HttpClient,
    Response,
)
from chumicro_requests.testing import (
    canned_response,
    drive_until_done,
    make_client,
)
from chumicro_sockets.testing import FakeSocket, FakeSocketConnector
from chumicro_timing.testing import FakeTicks


class TestHttpClientGet:
    """End-to-end GET against FakeSocket — happy path + structure."""

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
        """``https://`` URLs route to the transport_factory with
        ``use_tls=True`` and skip the port in the Host header when
        it equals 443 (the scheme default)."""
        socket = FakeSocket()
        socket.enqueue_recv(canned_response(body=b"secured"))
        captured = []

        def factory(host, port, use_tls):
            captured.append((host, port, use_tls))
            return FakeSocketConnector(actions=["dns_ok", "tcp_ok"], socket=socket)

        ticks = FakeTicks()
        client = HttpClient(
            transport_factory=factory,
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
            return FakeSocketConnector(actions=["dns_ok", "tcp_ok"], socket=socket)

        ticks = FakeTicks()
        client = HttpClient(
            transport_factory=factory,
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
