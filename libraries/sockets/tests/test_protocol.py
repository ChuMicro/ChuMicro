"""Conformance tests for the TCPClientSocket protocol surface."""

from chumicro_sockets import TCPClientSocket
from chumicro_sockets.testing import FakeSocket


class TestProtocolConformance:
    def test_fakesocket_satisfies_protocol(self) -> None:
        """FakeSocket implements every method the protocol declares."""
        sock = FakeSocket()
        assert isinstance(sock, TCPClientSocket)

    def test_protocol_attributes_called(self) -> None:
        """Each protocol method exists on the fake and returns the right shape."""
        sock = FakeSocket()
        # send returns int.
        assert isinstance(sock.send(b"hello"), int)
        # recv_into accepts a buffer + nbytes.
        sock.enqueue_recv(b"world")
        buffer = bytearray(8)
        nbytes_read = sock.recv_into(buffer, 5)
        assert isinstance(nbytes_read, int)
        # close idempotent.
        sock.close()
        sock.close()
        # blocking flags accept bool.
        sock_two = FakeSocket()
        sock_two.setblocking(False)
        sock_two.settimeout(1.5)
        # fileno returns int.
        assert isinstance(sock_two.fileno(), int)


class TestRuntimeCheckable:
    """`isinstance(sock, TCPClientSocket)` works at runtime."""

    def test_real_dict_is_not_a_socket(self) -> None:
        # Sanity — a plain dict obviously doesn't satisfy the protocol.
        assert not isinstance({"fake": True}, TCPClientSocket)

    def test_partial_implementation_rejected(self) -> None:
        class _Partial:
            def send(self, data: bytes) -> int:
                return len(data)
            # Missing every other method.

        assert not isinstance(_Partial(), TCPClientSocket)

    def test_full_duck_typed_passes(self) -> None:
        class _DuckSocket:
            def send(self, data: bytes) -> int:
                return len(data)

            def recv_into(self, buffer: bytearray, nbytes: int = 0) -> int:
                return 0

            def close(self) -> None:
                pass

            def setblocking(self, flag: bool) -> None:
                pass

            def settimeout(self, seconds: float | None) -> None:
                pass

            def fileno(self) -> int:
                return -1

        assert isinstance(_DuckSocket(), TCPClientSocket)
