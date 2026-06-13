"""Cross-runtime tests for chumicro_sockets UDP support.

:class:`FakeUDPSocket` — the in-memory protocol-conformance fake.
Every assertion here runs on CPython, MicroPython unix-port,
CircuitPython unix-port, and real boards.

Factory-routing tests — which swap ``chumicro_sockets._adapter`` and
assert ``udp_socket``'s dispatch target — moved to the host-only
``test_udp_routing.py``: a named adapter only stages on the matching
runtime, so those can't run on real silicon.  The CPython-loopback
tests (real ``socket.socket()``, ``getsockopt``, ``SO_BROADCAST``)
live in ``test_udp_pytest.py`` because they depend on stdlib ``socket``
directly — CP unix-port doesn't ship it (real CP boards use
``socketpool`` instead) and MP unix-port has it but the cross-runtime
contract is already covered by ``FakeUDPSocket`` plus the on-device
functional tests.

Cross-runtime files (no ``_pytest`` suffix) must not import pytest /
unittest / etc., and run unmodified under CPython + MicroPython +
CircuitPython unix-ports via the ``chumicro_test_harness`` runner.
"""

import errno

import chumicro_sockets
from chumicro_sockets.testing import FakeUDPSocket
from chumicro_test_harness.assertions import raises

# ---------------------------------------------------------------------------
# Public-surface checks
# ---------------------------------------------------------------------------


def test_udp_socket_factory_in_public_namespace() -> None:
    assert hasattr(chumicro_sockets, "udp_socket")


# ---------------------------------------------------------------------------
# FakeUDPSocket
# ---------------------------------------------------------------------------


class TestFakeUDPSocket:
    """In-memory protocol conformance tests."""

    def test_default_state(self) -> None:
        sock = FakeUDPSocket()
        assert sock.sent == []
        assert sock.closed is False
        assert sock.blocking is True

    def test_sendto_records_data_and_destination(self) -> None:
        sock = FakeUDPSocket()
        n_sent = sock.sendto(b"hello", "10.0.0.1", 1234)
        assert n_sent == 5
        assert sock.sent == [(b"hello", "10.0.0.1", 1234)]

    def test_sendto_accepts_bytes_like(self) -> None:
        sock = FakeUDPSocket()
        sock.sendto(bytearray(b"a"), "h", 1)
        sock.sendto(memoryview(b"b"), "h", 1)
        assert [data for data, _, _ in sock.sent] == [b"a", b"b"]

    def test_recvfrom_into_pops_queued_datagram(self) -> None:
        sock = FakeUDPSocket()
        sock.enqueue_recv(b"reply", host="10.0.0.5", port=5353)
        buffer = bytearray(64)
        n_received, address = sock.recvfrom_into(buffer)
        assert n_received == 5
        assert bytes(buffer[:5]) == b"reply"
        assert address == ("10.0.0.5", 5353)

    def test_recvfrom_into_truncates_to_buffer(self) -> None:
        sock = FakeUDPSocket()
        sock.enqueue_recv(b"abcdefghij")
        buffer = bytearray(4)
        n_received, _address = sock.recvfrom_into(buffer)
        assert n_received == 4
        assert bytes(buffer) == b"abcd"

    def test_recvfrom_into_respects_explicit_nbytes(self) -> None:
        sock = FakeUDPSocket()
        sock.enqueue_recv(b"abcdefghij")
        buffer = bytearray(64)
        n_received, _address = sock.recvfrom_into(buffer, nbytes=3)
        assert n_received == 3
        assert bytes(buffer[:3]) == b"abc"

    def test_recvfrom_into_empty_queue_raises_eagain(self) -> None:
        # An empty queue is "no datagram ready", which a real non-blocking
        # UDP socket reports as OSError(EAGAIN), not a zero-length read.
        sock = FakeUDPSocket()
        buffer = bytearray(16)
        with raises(OSError):
            sock.recvfrom_into(buffer)

    def test_recvfrom_into_zero_length_datagram_returns_zero(self) -> None:
        # A genuine zero-length datagram still returns 0 (distinct from an
        # empty queue), so a consumer can tell "0-byte packet" from "no
        # packet".
        sock = FakeUDPSocket()
        sock.enqueue_recv(b"", host="10.0.0.5", port=123)
        buffer = bytearray(16)
        n_received, address = sock.recvfrom_into(buffer)
        assert n_received == 0
        assert address == ("10.0.0.5", 123)

    def test_recvfrom_into_zero_capacity_returns_zero(self) -> None:
        sock = FakeUDPSocket()
        sock.enqueue_recv(b"reply")
        buffer = bytearray(0)
        n_received, _address = sock.recvfrom_into(buffer)
        assert n_received == 0

    def test_enqueue_recv_rejects_non_bytes_like(self) -> None:
        sock = FakeUDPSocket()
        with raises(TypeError):
            sock.enqueue_recv("not bytes")  # type: ignore[arg-type]

    def test_eagain_for_send(self) -> None:
        sock = FakeUDPSocket()
        sock.enqueue_eagain_for_send(2)
        with raises(OSError) as first:
            sock.sendto(b"x", "h", 1)
        assert first.value.args[0] == errno.EAGAIN
        with raises(OSError):
            sock.sendto(b"x", "h", 1)
        # Third send succeeds.
        sock.sendto(b"x", "h", 1)
        assert len(sock.sent) == 1

    def test_eagain_for_recv(self) -> None:
        sock = FakeUDPSocket()
        sock.enqueue_eagain_for_recv(1)
        sock.enqueue_recv(b"x")
        buffer = bytearray(8)
        with raises(OSError) as raised:
            sock.recvfrom_into(buffer)
        assert raised.value.args[0] == errno.EAGAIN
        n_received, _address = sock.recvfrom_into(buffer)
        assert n_received == 1

    def test_close_and_subsequent_calls_raise_ebadf(self) -> None:
        sock = FakeUDPSocket()
        sock.close()
        assert sock.closed is True
        with raises(OSError) as send_raised:
            sock.sendto(b"x", "h", 1)
        assert send_raised.value.args[0] == 9
        buffer = bytearray(8)
        with raises(OSError):
            sock.recvfrom_into(buffer)
        # Repeated close is idempotent.
        sock.close()

    def test_setblocking_and_settimeout_track_state(self) -> None:
        sock = FakeUDPSocket()
        sock.setblocking(False)
        assert sock.blocking is False
        sock.settimeout(2.5)
        assert sock.blocking is False
        sock.settimeout(None)
        assert sock.blocking is True

    def test_getsockname_reports_bind_address(self) -> None:
        sock = FakeUDPSocket(bind_host="192.168.1.10", bind_port=1234)
        assert sock.getsockname() == ("192.168.1.10", 1234)
