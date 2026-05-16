"""CPython-only positive assertions for ``isinstance(..., TCPClientSocket)``.

These cases verify ``typing.runtime_checkable``-backed structural
matching — i.e. that ``isinstance(sock, TCPClientSocket)`` returns
``True`` for any object exposing the right method names.  This only
works under real ``typing.Protocol``, which is CPython-only on the
unix ports we target (the MP / CP fallback in
:mod:`chumicro_sockets.protocol` is a plain class stub).

The negative assertions (dict isn't a socket; partial impl isn't a
socket) live in ``test_protocol.py`` — they're true under both the
real Protocol and the stand-in.
"""

#: CPython-only lane (pytest fixtures / host stdlib); not cross-runtime.
__chumicro_runtimes__ = ("cpython",)

from chumicro_sockets import TCPClientSocket
from chumicro_sockets.testing import FakeSocket


class TestProtocolConformance:
    def test_fakesocket_satisfies_protocol(self) -> None:
        """FakeSocket implements every method the protocol declares."""
        sock = FakeSocket()
        assert isinstance(sock, TCPClientSocket)


class TestRuntimeCheckable:
    """Positive assertions for runtime-checkable structural matching."""

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
