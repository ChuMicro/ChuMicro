"""CPython-only loopback UDP tests for chumicro_sockets.

These tests open real UDP sockets via stdlib ``socket`` (loopback,
ephemeral ports), drive ``sendto`` / ``recvfrom_into`` end-to-end,
and probe ``getsockopt`` for ``SO_BROADCAST``.  All three are
CPython-runtime-detail concerns:

* MicroPython unix-port has stdlib ``socket`` and could in principle
  run them, but we already exercise the cross-runtime UDP contract
  via ``FakeUDPSocket`` in ``test_udp.py`` and against real boards
  in ``libraries/ntp/functional_tests/test_real_ntp.py``.
* CircuitPython unix-port doesn't ship stdlib ``socket`` at all
  (real CP boards expose ``socketpool`` instead, which the ``cp``
  adapter wraps), so the tests would ``ImportError``-SKIP there.
* The ``getsockopt`` / ``SO_BROADCAST`` probes reach into the
  CPython wrapper's private ``_sock`` attribute — that wrapper
  doesn't exist on the CP / MP adapters.

The cross-runtime layers (``FakeUDPSocket`` + factory routing) live
in the sibling ``test_udp.py``.
"""

#: CPython-only lane (pytest fixtures / host stdlib); not cross-runtime.
__chumicro_runtimes__ = ("cpython",)

import socket

import pytest
from chumicro_sockets import udp_socket


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
        # POSIX: a closed socket reports fileno() as -1.  Confirms the
        # close actually took effect (vs. silently no-oping).
        assert sock.fileno() == -1

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
