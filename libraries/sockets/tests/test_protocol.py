"""Conformance tests for the TCPClientSocket protocol surface.

The two ``isinstance(..., TCPClientSocket)`` positive-assertion tests
live in ``test_protocol_pytest.py`` — they rely on
``typing.runtime_checkable``-backed structural matching, which only
exists on CPython.  MP / CP unix-ports use the ``Protocol`` stand-in
in :mod:`chumicro_sockets.protocol` (no ``typing`` module), where
``isinstance`` against an unrelated class is always ``False``.

The negative-assertion conformance checks (a dict isn't a socket; a
partial-implementation class isn't a socket) work on every runtime —
they're true under both real Protocol and the stand-in.
"""

from chumicro_sockets import TCPClientSocket
from chumicro_sockets.testing import FakeSocket


class TestProtocolConformance:
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
    """Negative-assertion checks — true under both real Protocol and the stand-in."""

    def test_real_dict_is_not_a_socket(self) -> None:
        # Sanity — a plain dict obviously doesn't satisfy the protocol.
        assert not isinstance({"fake": True}, TCPClientSocket)

    def test_partial_implementation_rejected(self) -> None:
        class _Partial:
            def send(self, data: bytes) -> int:
                return len(data)
            # Missing every other method.

        assert not isinstance(_Partial(), TCPClientSocket)
