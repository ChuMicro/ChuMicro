"""Tests for chumicro_sockets UDP support.

Three layers:

* CPython adapter against a real loopback UDP socket — the ground truth
  for the protocol contract (real ``recvfrom_into`` returning
  ``(nbytes, (host, port))``, real ``sendto`` accepting separated
  ``host`` / ``port``).
* ``FakeUDPSocket`` driving the same surface in-memory.
* Factory routing — confirm ``udp_socket`` dispatches to the right
  adapter via patched ``sys.implementation.name``.

Per Decision 0009 each library's tests run in a separate pytest
subprocess; this file is one of two driving the sockets coverage gate.
"""

import socket
from unittest import mock

import chumicro_sockets
import pytest
from chumicro_sockets import UDPSocket, udp_socket
from chumicro_sockets.testing import FakeUDPSocket

# ---------------------------------------------------------------------------
# Public-surface checks
# ---------------------------------------------------------------------------


def test_udp_socket_factory_in_public_namespace() -> None:
    assert hasattr(chumicro_sockets, "udp_socket")
    assert hasattr(chumicro_sockets, "UDPSocket")
    assert chumicro_sockets.UDPSocket is UDPSocket


# ---------------------------------------------------------------------------
# CPython adapter — real loopback UDP
# ---------------------------------------------------------------------------


class TestCPythonUDP:
    """End-to-end: bind two UDP sockets on loopback, send between them."""

    def test_factory_returns_bound_socket(self) -> None:
        sock = udp_socket("127.0.0.1", 0)
        try:
            host, port = sock.getsockname()
            assert host == "127.0.0.1"
            assert port > 0  # OS-assigned ephemeral
            assert sock.fileno() > 0
        finally:
            sock.close()

    def test_sendto_and_recvfrom_round_trip(self) -> None:
        sender = udp_socket("127.0.0.1", 0)
        receiver = udp_socket("127.0.0.1", 0)
        try:
            receiver_address = receiver.getsockname()
            n_sent = sender.sendto(b"hello", receiver_address[0], receiver_address[1])
            assert n_sent == 5

            buffer = bytearray(64)
            n_received, sender_address = receiver.recvfrom_into(buffer)
            assert n_received == 5
            assert bytes(buffer[:5]) == b"hello"
            # Sender's reported address matches what the OS bound for
            # the sender socket (loopback + the sender's ephemeral port).
            assert sender_address[0] == "127.0.0.1"
            assert sender_address[1] == sender.getsockname()[1]
        finally:
            sender.close()
            receiver.close()

    def test_recvfrom_into_truncates_oversized_datagram(self) -> None:
        """Buffer smaller than datagram → unread tail discarded (UDP)."""
        sender = udp_socket("127.0.0.1", 0)
        receiver = udp_socket("127.0.0.1", 0)
        try:
            receiver_address = receiver.getsockname()
            sender.sendto(b"abcdefghij", receiver_address[0], receiver_address[1])

            buffer = bytearray(4)
            n_received, _address = receiver.recvfrom_into(buffer)
            assert n_received == 4
            assert bytes(buffer) == b"abcd"
        finally:
            sender.close()
            receiver.close()

    def test_recvfrom_into_respects_explicit_nbytes(self) -> None:
        sender = udp_socket("127.0.0.1", 0)
        receiver = udp_socket("127.0.0.1", 0)
        try:
            receiver_address = receiver.getsockname()
            sender.sendto(b"abcdefghij", receiver_address[0], receiver_address[1])

            buffer = bytearray(64)
            n_received, _address = receiver.recvfrom_into(buffer, nbytes=3)
            assert n_received == 3
            assert bytes(buffer[:3]) == b"abc"
        finally:
            sender.close()
            receiver.close()

    def test_setblocking_false_raises_eagain_on_no_data(self) -> None:
        receiver = udp_socket("127.0.0.1", 0)
        try:
            receiver.setblocking(False)
            buffer = bytearray(16)
            with pytest.raises(OSError) as raised:
                receiver.recvfrom_into(buffer)
            # Different platforms use different EAGAIN-equivalents; any
            # would-block code is acceptable.
            assert raised.value.args[0] in (11, 35, 10035)
        finally:
            receiver.close()

    def test_settimeout_raises_oserror_after_window(self) -> None:
        receiver = udp_socket("127.0.0.1", 0)
        try:
            receiver.settimeout(0.05)
            buffer = bytearray(16)
            with pytest.raises(OSError):
                receiver.recvfrom_into(buffer)
        finally:
            receiver.close()

    def test_close_is_idempotent(self) -> None:
        sock = udp_socket("127.0.0.1", 0)
        sock.close()
        sock.close()  # second close: no exception.

    def test_broadcast_flag_sets_so_broadcast(self) -> None:
        """``broadcast=True`` allows sendto to a broadcast address."""
        sock = udp_socket("0.0.0.0", 0, broadcast=True)
        try:
            # Verify SO_BROADCAST is enabled on the underlying socket.
            value = sock._sock.getsockopt(  # noqa: SLF001 — testing the wrapper
                socket.SOL_SOCKET,
                socket.SO_BROADCAST,
            )
            assert value != 0
        finally:
            sock.close()

    def test_broadcast_default_off(self) -> None:
        sock = udp_socket("0.0.0.0", 0)
        try:
            value = sock._sock.getsockopt(  # noqa: SLF001 — testing the wrapper
                socket.SOL_SOCKET,
                socket.SO_BROADCAST,
            )
            assert value == 0
        finally:
            sock.close()


# ---------------------------------------------------------------------------
# FakeUDPSocket
# ---------------------------------------------------------------------------


class TestFakeUDPSocket:
    """In-memory protocol conformance tests."""

    def test_default_state(self) -> None:
        sock = FakeUDPSocket()
        assert sock.sent == []
        assert sock.pending_recv_chunks == 0
        assert sock.closed is False
        assert sock.blocking is True
        assert sock.timeout is None

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

    def test_recvfrom_into_empty_queue_returns_zero(self) -> None:
        sock = FakeUDPSocket()
        buffer = bytearray(16)
        n_received, address = sock.recvfrom_into(buffer)
        assert n_received == 0
        assert address == ("0.0.0.0", 0)

    def test_recvfrom_into_zero_capacity_returns_zero(self) -> None:
        sock = FakeUDPSocket()
        sock.enqueue_recv(b"reply")
        buffer = bytearray(0)
        n_received, _address = sock.recvfrom_into(buffer)
        assert n_received == 0

    def test_enqueue_recv_rejects_non_bytes_like(self) -> None:
        sock = FakeUDPSocket()
        with pytest.raises(TypeError):
            sock.enqueue_recv("not bytes")  # type: ignore[arg-type]

    def test_eagain_for_send(self) -> None:
        sock = FakeUDPSocket()
        sock.enqueue_eagain_for_send(2)
        with pytest.raises(OSError) as first:
            sock.sendto(b"x", "h", 1)
        assert first.value.args[0] == 11
        with pytest.raises(OSError):
            sock.sendto(b"x", "h", 1)
        # Third send succeeds.
        sock.sendto(b"x", "h", 1)
        assert len(sock.sent) == 1

    def test_eagain_for_recv(self) -> None:
        sock = FakeUDPSocket()
        sock.enqueue_eagain_for_recv(1)
        sock.enqueue_recv(b"x")
        buffer = bytearray(8)
        with pytest.raises(OSError) as raised:
            sock.recvfrom_into(buffer)
        assert raised.value.args[0] == 11
        n_received, _address = sock.recvfrom_into(buffer)
        assert n_received == 1

    def test_close_and_subsequent_calls_raise_ebadf(self) -> None:
        sock = FakeUDPSocket()
        sock.close()
        assert sock.closed is True
        with pytest.raises(OSError) as send_raised:
            sock.sendto(b"x", "h", 1)
        assert send_raised.value.args[0] == 9
        buffer = bytearray(8)
        with pytest.raises(OSError):
            sock.recvfrom_into(buffer)
        # Repeated close is idempotent.
        sock.close()

    def test_setblocking_and_settimeout_track_state(self) -> None:
        sock = FakeUDPSocket()
        sock.setblocking(False)
        assert sock.blocking is False
        assert sock.timeout == 0.0
        sock.settimeout(2.5)
        assert sock.timeout == 2.5
        assert sock.blocking is False
        sock.settimeout(None)
        assert sock.timeout is None
        assert sock.blocking is True

    def test_getsockname_reports_bind_address(self) -> None:
        sock = FakeUDPSocket(bind_host="192.168.1.10", bind_port=1234)
        assert sock.getsockname() == ("192.168.1.10", 1234)

    def test_fileno_default_is_positive(self) -> None:
        sock = FakeUDPSocket()
        assert sock.fileno() >= 0

    def test_fileno_can_be_overridden(self) -> None:
        sock = FakeUDPSocket()
        sock.set_fileno(-1)
        assert sock.fileno() == -1

    def test_pending_recv_chunks_counts_queue(self) -> None:
        sock = FakeUDPSocket()
        sock.enqueue_recv(b"a")
        sock.enqueue_recv(b"b")
        assert sock.pending_recv_chunks == 2


# ---------------------------------------------------------------------------
# Factory routing — confirm udp_socket dispatches by runtime
# ---------------------------------------------------------------------------


class TestUDPFactoryRouting:
    """Verify ``udp_socket`` picks the right adapter via ``_runtime_name``."""

    def test_routes_to_circuitpython(self) -> None:
        sentinel = object()
        with mock.patch.object(chumicro_sockets, "_runtime_name", return_value="circuitpython"):
            with mock.patch(
                "chumicro_sockets._adapters.cp.udp_socket",
                return_value=sentinel,
                create=True,
            ) as patched:
                result = udp_socket(
                    "0.0.0.0",
                    1234,
                    radio="radio-stub",
                    broadcast=True,
                )
        patched.assert_called_once_with(
            bind_host="0.0.0.0",
            bind_port=1234,
            radio="radio-stub",
            broadcast=True,
        )
        assert result is sentinel

    def test_routes_to_micropython(self) -> None:
        sentinel = object()
        with mock.patch.object(chumicro_sockets, "_runtime_name", return_value="micropython"):
            with mock.patch(
                "chumicro_sockets._adapters.mp.udp_socket",
                return_value=sentinel,
                create=True,
            ) as patched:
                result = udp_socket("1.2.3.4", 9, broadcast=True)
        patched.assert_called_once_with(
            bind_host="1.2.3.4",
            bind_port=9,
            broadcast=True,
        )
        assert result is sentinel

    def test_routes_to_cpython_for_unknown_runtime(self) -> None:
        sentinel = object()
        with mock.patch.object(chumicro_sockets, "_runtime_name", return_value="pypy"):
            with mock.patch(
                "chumicro_sockets._adapters.cpython.udp_socket",
                return_value=sentinel,
                create=True,
            ) as patched:
                result = udp_socket()
        patched.assert_called_once_with(
            bind_host="0.0.0.0",
            bind_port=0,
            broadcast=False,
        )
        assert result is sentinel
