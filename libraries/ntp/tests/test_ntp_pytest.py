"""CPython-only tests for the UDP socket chumicro_ntp wires by default.

These cases exercise the ``_CPythonUDPWrapper`` that
``chumicro_sockets.sockets_factory.udp_socket_factory()()`` yields on
CPython — the same default wiring ``NTPClient.from_config`` builds —
binding a real UDP socket on the host and asserting its ephemeral bound
port plus the ``sendto`` / ``recvfrom_into`` surface.  They have no
cross-runtime equivalent at the unit level:

* CircuitPython's ``udp_socket_factory()`` requires a ``radio=``
  argument (typically ``wifi.radio``), which doesn't exist on the CP
  unix-port.
* MicroPython's wrapper exposes a different socket surface.

The cross-runtime contract — "factory returns a working UDP socket
bound to an ephemeral port, with ``sendto`` / ``recvfrom_into`` /
``getsockname``" — is exercised on real hardware in
``functional_tests/test_real_ntp.py``.
"""

#: CPython-only lane (pytest fixtures / host stdlib); not cross-runtime.
__chumicro_runtimes__ = ("cpython",)

from chumicro_sockets.sockets_factory import udp_socket_factory


def test_udp_socket_factory_returns_chumicro_sockets_udp_socket() -> None:
    """Building the default factory returns a ``udp_socket``-shaped wrapper."""
    sock = udp_socket_factory()()
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
