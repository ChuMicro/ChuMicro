"""Shared redirect-test helpers for the requests client redirect suites.

Underscore-prefixed so pytest does not collect it as a test module; the
tests' own directory is on ``sys.path`` on host, unix-port, and device,
so ``from _redirect_helpers import ...`` resolves everywhere.
"""

from chumicro_sockets.testing import FakeSocketConnector


def canned_redirect(*, status=301, location="/", reason="Moved"):
    """Build an HTTP/1.1 3xx redirect response byte-string."""
    return (
        f"HTTP/1.1 {status} {reason}\r\n"
        f"Location: {location}\r\n"
        "Content-Length: 0\r\n"
        "\r\n"
    ).encode("ascii")


def _factory_for_socket_sequence(sockets):
    """Return a transport_factory that hands out *sockets* FIFO,
    wrapped in scripted FakeSocketConnectors."""
    cursor = {"index": 0}

    def factory(host, port, use_tls):  # noqa: ARG001
        socket = sockets[cursor["index"]]
        cursor["index"] += 1
        return FakeSocketConnector(actions=["dns_ok", "tcp_ok"], socket=socket)

    return factory
