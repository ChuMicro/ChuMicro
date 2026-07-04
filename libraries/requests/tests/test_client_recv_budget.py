"""requests client: recv budget per tick keeps each tick LED-friendly."""

from chumicro_requests.testing import (
    canned_response,
    drive_until_done,
    make_client,
)
from chumicro_sockets.testing import FakeSocket


class _CountingSocket(FakeSocket):
    """FakeSocket that records bytes consumed per recv_into call."""

    def __init__(self):
        super().__init__()
        self.bytes_received_total = 0

    def recv_into(self, buffer, nbytes=0):
        result = super().recv_into(buffer, nbytes)
        if result > 0:
            self.bytes_received_total += result
        return result


class TestHttpClientRecvBudget:
    """``recv_budget_per_tick`` keeps each tick LED-friendly."""

    def test_budget_caps_bytes_per_tick(self):
        body = b"x" * 4096
        socket = _CountingSocket()
        socket.enqueue_recv(canned_response(body=body))
        client, ticks, _ = make_client(
            socket_or_factory=socket,
            recv_budget_per_tick=512,
            max_body_bytes=8192,
        )
        handle = client.get("http://example.test/")
        # Drive sending only — first tick handles SENDING + transitions to RECEIVING.
        client.handle(ticks.ticks_ms())  # SEND
        socket.bytes_received_total = 0
        client.handle(ticks.ticks_ms())  # RECV (one tick)
        assert socket.bytes_received_total <= 512
        assert not handle.done

    def test_default_budget_is_1024(self):
        socket = _CountingSocket()
        socket.enqueue_recv(canned_response(body=b"x" * 8192))
        client, ticks, _ = make_client(
            socket_or_factory=socket, max_body_bytes=16384,
        )
        handle = client.get("http://example.test/")
        client.handle(ticks.ticks_ms())  # SEND
        socket.bytes_received_total = 0
        client.handle(ticks.ticks_ms())  # RECV (one tick)
        assert socket.bytes_received_total <= 1024
        assert not handle.done

    def test_budget_eventually_drains_full_payload(self):
        body = b"y" * 4096
        socket = _CountingSocket()
        socket.enqueue_recv(canned_response(body=body))
        client, ticks, _ = make_client(
            socket_or_factory=socket,
            recv_budget_per_tick=1024,
            max_body_bytes=8192,
        )
        handle = client.get("http://example.test/")
        drive_until_done(client, handle, ticks, max_ticks=20)
        assert handle.result.body == body
