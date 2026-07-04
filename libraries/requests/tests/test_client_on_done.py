"""requests client: on_done callback binds response handling to the
request that produced it — success, error, follow-up, propagation.
"""

import errno

from chumicro_requests import (
    HttpClient,
    HttpError,
)
from chumicro_requests.testing import (
    canned_response,
    drive_until_done,
    make_client,
    make_factory,
)
from chumicro_sockets.testing import FakeSocket
from chumicro_timing.testing import FakeTicks


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
            transport_factory=make_factory(lambda: next(sockets)),
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

    def test_callback_exception_propagates_not_swallowed(self):
        # A callback raising HttpError must surface to the driving loop,
        # not be caught by handle()'s HttpError handler and dropped.
        socket = FakeSocket()
        socket.enqueue_recv(canned_response(body=b"hi"))
        client, ticks, _ = make_client(socket_or_factory=socket)

        def on_done(_handle):
            raise HttpError("callback boom")

        handle = client.get("http://example.test/", on_done=on_done)
        raised = None
        for _ in range(50):
            try:
                client.handle(ticks.ticks_ms())
            except HttpError as boom:
                raised = boom
                break
            ticks.advance(1)

        assert raised is not None
        assert "callback boom" in str(raised)
        assert handle.result.body == b"hi"  # request itself succeeded

    def test_callback_raise_spares_follow_up_request(self):
        # A callback that issues a follow-up request and then raises must
        # not have its exception destroy that follow-up: the new request
        # survives and can still be driven to completion.
        first = FakeSocket()
        first.enqueue_recv(canned_response(body=b"one"))
        second = FakeSocket()
        second.enqueue_recv(canned_response(body=b"two"))
        sockets = iter((first, second))
        ticks = FakeTicks()
        client = HttpClient(
            transport_factory=make_factory(lambda: next(sockets)),
            ticks=ticks,
        )

        follow_up = []

        def on_first_done(_handle):
            follow_up.append(client.get("http://example.test/again"))
            raise HttpError("callback boom")

        first_handle = client.get(
            "http://example.test/", on_done=on_first_done,
        )
        raised = None
        for _ in range(50):
            try:
                client.handle(ticks.ticks_ms())
            except HttpError as boom:
                raised = boom
                break
            ticks.advance(1)

        assert raised is not None
        assert first_handle.result.body == b"one"
        assert len(follow_up) == 1
        follow_up_handle = follow_up[0]
        assert follow_up_handle.error is None
        drive_until_done(client, follow_up_handle, ticks)
        assert follow_up_handle.result.body == b"two"
