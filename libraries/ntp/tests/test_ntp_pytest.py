"""CPython-only tests for chumicro_ntp.sockets_factory.

These cases exercise the ``_CPythonUDPWrapper`` returned by
``chumicro_sockets_factory()`` on CPython — including its private
``_sock`` attribute and ``getsockopt`` round-trips against the stdlib
``socket`` module.  They have no cross-runtime equivalent at the unit
level:

* CircuitPython's ``chumicro_sockets_factory()`` requires a
  ``radio=`` argument (typically ``wifi.radio``), which doesn't
  exist on the CP unix-port.
* MicroPython's stdlib socket exposes a different surface for
  ``getsockopt`` and there's no ``_sock`` attribute on the wrapper.

The cross-runtime contract — "factory returns a working UDP socket
bound to an ephemeral port, with ``sendto`` / ``recvfrom_into`` /
``getsockname``" — is exercised on real hardware in
``functional_tests/test_real_ntp.py``.
"""

#: CPython-only lane (pytest fixtures / host stdlib); not cross-runtime.
__chumicro_runtimes__ = ("cpython",)

import socket as stdlib_socket

from chumicro_ntp.sockets_factory import chumicro_sockets_factory


def test_sockets_factory_returns_chumicro_sockets_udp_socket() -> None:
    """Importing the factory submodule returns a ``udp_socket``-shaped wrapper."""
    sock = chumicro_sockets_factory()
    try:
        # Bound to an ephemeral port on every interface (default args).
        host, port = sock.getsockname()
        assert host == "0.0.0.0"
        assert port > 0
        # Has the UDP protocol surface — sendto + recvfrom_into present.
        assert callable(sock.sendto)
        assert callable(sock.recvfrom_into)
    finally:
        sock.close()


def test_sockets_factory_passes_through_broadcast_flag() -> None:
    sock = chumicro_sockets_factory(broadcast=True)
    try:
        # CPython exposes the wrapped socket directly on the
        # _CPythonUDPWrapper; test the SO_BROADCAST round-trip via
        # the underlying stdlib socket.
        value = sock._sock.getsockopt(  # noqa: SLF001 — testing the wrapper
            stdlib_socket.SOL_SOCKET,
            stdlib_socket.SO_BROADCAST,
        )
        assert value != 0
    finally:
        sock.close()
