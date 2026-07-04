"""requests client: ``WhenOversized`` policy branches — drop / event / fail."""

from chumicro_requests import (
    HttpOversizedError,
    WhenOversized,
)
from chumicro_requests.testing import (
    canned_response,
    drive_until_done,
    make_client,
)
from chumicro_sockets.testing import FakeSocket


class TestHttpClientOversizePolicy:
    """``WhenOversized`` branches: silent drop, drop+event, fail."""

    def test_drop_silent_yields_empty_body(self):
        body = b"x" * 100
        socket = FakeSocket()
        socket.enqueue_recv(canned_response(body=body))
        client, ticks, _ = make_client(
            socket_or_factory=socket,
            max_body_bytes=10,
            when_oversized=WhenOversized.DROP_SILENT,
        )
        handle = client.get("http://example.test/")
        drive_until_done(client, handle, ticks)

        response = handle.result
        assert response.body == b""
        assert response.oversized_dropped is True
        assert response.status_code == 200

    def test_drop_with_event_fires_callback(self):
        body = b"x" * 100
        socket = FakeSocket()
        socket.enqueue_recv(canned_response(body=body))
        client, ticks, _ = make_client(
            socket_or_factory=socket,
            max_body_bytes=10,
            when_oversized=WhenOversized.DROP_WITH_EVENT,
        )
        events = []
        client.on_oversized = lambda reported_length, url: events.append((reported_length, url))

        handle = client.get("http://example.test/")
        drive_until_done(client, handle, ticks)

        assert handle.result.oversized_dropped is True
        assert len(events) == 1
        assert events[0][0] == 100
        assert events[0][1] == "http://example.test/"

    def test_disconnect_policy_fails_request(self):
        body = b"x" * 100
        socket = FakeSocket()
        socket.enqueue_recv(canned_response(body=body))
        client, ticks, _ = make_client(
            socket_or_factory=socket,
            max_body_bytes=10,
            when_oversized=WhenOversized.DISCONNECT,
        )
        handle = client.get("http://example.test/")
        drive_until_done(client, handle, ticks)

        assert isinstance(handle.error, HttpOversizedError)
        assert handle.error.reported_length == 100
