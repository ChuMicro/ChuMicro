"""requests client: response decode, GET, runner contract."""

import errno
import select

from chumicro_requests import (
    CaseInsensitiveDict,
    HttpClient,
    Response,
)
from chumicro_requests.testing import (
    canned_response,
    drive_until_done,
    make_client,
    make_factory,
)
from chumicro_runner import Runner
from chumicro_runner.testing import FakePoller
from chumicro_sockets.testing import FakeSocket, FakeSocketConnector
from chumicro_test_harness.assertions import raises
from chumicro_timing.testing import FakeTicks


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
        """``https://`` URLs route to the connector_factory with
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
            connector_factory=factory,
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
            connector_factory=factory,
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


class TestRunnerReactorContract:
    """``io_socket`` / ``io_wants_read`` / ``io_wants_write`` /
    ``next_deadline`` let ``Runner.wait`` register the in-flight socket
    and sleep until its readiness or the request timeout."""

    def test_io_socket_none_when_idle(self):
        client, _ticks, _ = make_client()
        assert client.io_socket is None

    def test_io_socket_returns_socket_in_flight(self):
        socket = FakeSocket()
        client, ticks, _ = make_client(socket_or_factory=socket)
        client.get("http://example.test/")
        # At ``awaiting_dns`` the connector has not built its socket, so
        # the pollable is ``None``; one ``handle`` drives ``dns_ok`` and
        # the connector's socket goes live.
        assert client.io_socket is None
        client.handle(ticks.ticks_ms())
        # FakeSocket has no ``_sock`` wrapping, so the property returns
        # the socket itself.  Production adapters expose ``_sock`` and
        # the property unwraps it for the poller.
        assert client.io_socket is socket

    def test_io_wants_write_only_during_send(self):
        socket = FakeSocket()
        # Stall the send so the request stays in SENDING.
        socket.enqueue_eagain_for_send(99)
        client, ticks, _ = make_client(socket_or_factory=socket)
        assert client.io_wants_write is False

        client.get("http://example.test/")
        client.handle(ticks.ticks_ms())  # drive into SENDING

        assert client.io_wants_write is True
        assert client.io_wants_read is False

    def test_io_wants_read_only_during_receive(self):
        socket = FakeSocket()
        # Stall the recv so the request stays in RECEIVING.  An empty
        # recv queue with no queued eagains would be a clean peer close
        # and would fail the request rather than stall.
        socket.enqueue_eagain_for_recv(99)
        client, ticks, _ = make_client(socket_or_factory=socket)
        client.get("http://example.test/")
        # First handle ticks the connector through dns_ok; second
        # through tcp_ok → promote → SENDING → drain → RECEIVING.
        client.handle(ticks.ticks_ms())
        client.handle(ticks.ticks_ms())

        assert client.io_wants_read is True
        assert client.io_wants_write is False

    def test_next_deadline_none_when_idle(self):
        client, ticks, _ = make_client()
        assert client.next_deadline(ticks.ticks_ms()) is None

    def test_next_deadline_clamps_to_now_while_awaiting_dns(self):
        """At request start the connector is in awaiting_dns with no
        socket, so io_socket is None and next_deadline collapses to
        now_ms — Runner.wait then ticks the connector forward instead
        of sleeping toward the far request deadline."""
        socket = FakeSocket()
        client, ticks, _ = make_client(
            socket_or_factory=socket, default_timeout_ms=500,
        )
        client.get("http://example.test/")

        assert client.io_socket is None
        assert client.next_deadline(777) == 777

    def test_next_deadline_returns_request_deadline_once_pollable(self):
        """Once one handle tick drives dns_ok and the connector exposes
        its socket, the clamp lifts and the per-request budget (500 ms
        from start) governs the wake again."""
        socket = FakeSocket()
        client, ticks, _ = make_client(
            socket_or_factory=socket, default_timeout_ms=500,
        )
        start = ticks.ticks_ms()
        client.get("http://example.test/")
        # Drive the connector one step: dns_ok makes io_socket live.
        client.handle(ticks.ticks_ms())

        assert client.io_socket is socket
        deadline = client.next_deadline(ticks.ticks_ms())
        assert deadline is not None
        assert ticks.ticks_diff(deadline, start) == 500

    def test_io_attributes_clear_after_request_completes(self):
        socket = FakeSocket()
        socket.enqueue_recv(canned_response(body=b"ok"))
        client, ticks, _ = make_client(socket_or_factory=socket)
        handle = client.get("http://example.test/")
        drive_until_done(client, handle, ticks)

        assert client.io_socket is None
        assert client.io_wants_read is False
        assert client.io_wants_write is False
        assert client.next_deadline(ticks.ticks_ms()) is None

    def test_runner_wait_registers_socket_for_writing_then_reading(self):
        """End-to-end: a request drives register(POLLOUT) on the first
        wait, modify to POLLIN once SENDING completes, then unregister
        when the request returns to IDLE."""
        socket = FakeSocket()
        # One send EAGAIN keeps SENDING visible for one wait() call
        # before the buffer drains; one recv EAGAIN keeps RECEIVING
        # visible for one wait() call before the body arrives.
        socket.enqueue_eagain_for_send(1)
        socket.enqueue_eagain_for_recv(1)
        socket.enqueue_recv(canned_response(body=b"ok"))
        ticks = FakeTicks()
        poller = FakePoller()
        runner = Runner(ticks=ticks, poller=poller)
        client = HttpClient(
            connector_factory=make_factory(socket), ticks=ticks,
        )
        runner.add(client)

        handle = client.get("http://example.test/")
        # Fire wait once before the first tick so wait observes the
        # initial SENDING state set by client.get(); then drive
        # tick / wait until the response is decoded.
        runner.wait(ticks.ticks_ms())
        for _ in range(40):
            now_ms = runner.tick()
            runner.wait(now_ms)
            if handle.done:
                break
            ticks.advance(1)

        assert handle.done is True
        # SENDING phase asked for POLLOUT.
        assert any(
            eventmask == select.POLLOUT
            for _sock, eventmask in poller.register_calls + poller.modify_calls
        )
        # RECEIVING phase asked for POLLIN.
        assert any(
            eventmask == select.POLLIN
            for _sock, eventmask in poller.register_calls + poller.modify_calls
        )
        # Completion unregistered the socket.
        assert socket in poller.unregister_calls


class _StalledRecvSocket(FakeSocket):
    """FakeSocket whose recv always raises EAGAIN, so requests stall
    until their per-request timeout fires."""

    def recv_into(self, buffer, nbytes=0):  # noqa: ARG002 — fake signature
        if self.closed:
            raise OSError(errno.EBADF, "socket closed")
        raise OSError(errno.EAGAIN, "would block")


class TestOnDoneCallback:
    """``on_done`` binds response handling to the request that produced it."""

    def test_callback_fires_on_success_with_handle(self):
        socket = FakeSocket()
        socket.enqueue_recv(canned_response(body=b"hi"))
        client, ticks, _ = make_client(socket_or_factory=socket)

        received = []
        handle = client.get(
            "http://example.test/", on_done=received.append,
        )
        drive_until_done(client, handle, ticks)

        assert received == [handle]
        assert received[0].result.body == b"hi"
        assert received[0].url == "http://example.test/"

    def test_callback_fires_on_error_with_handle(self):
        socket = _StalledRecvSocket()
        client, ticks, _ = make_client(socket_or_factory=socket)

        received = []
        handle = client.get(
            "http://example.test/", timeout_ms=50, on_done=received.append,
        )
        for _ in range(60):
            if handle.done:
                break
            client.handle(ticks.ticks_ms())
            ticks.advance(2)

        assert received == [handle]
        assert received[0].error is not None

    def test_callback_sees_idle_client_and_may_issue_next(self):
        first = FakeSocket()
        first.enqueue_recv(canned_response(body=b"one"))
        second = FakeSocket()
        second.enqueue_recv(canned_response(body=b"two"))
        sockets = iter((first, second))
        ticks = FakeTicks()
        client = HttpClient(
            connector_factory=make_factory(lambda: next(sockets)),
            ticks=ticks,
        )

        busy_in_callback = []
        second_handle = []

        def on_first_done(_handle):
            busy_in_callback.append(client.busy)
            second_handle.append(client.get("http://example.test/again"))

        first_handle = client.get(
            "http://example.test/", on_done=on_first_done,
        )
        drive_until_done(client, first_handle, ticks)

        assert busy_in_callback == [False]
        drive_until_done(client, second_handle[0], ticks)
        assert second_handle[0].result.body == b"two"

    def test_no_callback_when_on_done_omitted(self):
        socket = FakeSocket()
        socket.enqueue_recv(canned_response(body=b"x"))
        client, ticks, _ = make_client(socket_or_factory=socket)
        handle = client.get("http://example.test/")
        drive_until_done(client, handle, ticks)
        assert handle.done is True  # poll path unaffected
