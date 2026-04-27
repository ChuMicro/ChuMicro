"""Cross-runtime TCP + TLS sockets for CircuitPython, MicroPython, and CPython.

Public API::

    from chumicro_sockets import (
        TCPClientSocket,           # protocol every adapter implements
        UnsupportedSSLConfigError, # raised when the requested TLS shape isn't supported
        tcp_client_socket,         # plain-TCP factory
        tls_client_socket,         # TLS factory
        ssl_context_with_ca,       # custom-CA helper
    )

    from chumicro_sockets.testing import FakeSocket

Per-runtime adapters live under ``_adapters/``; two sibling factories
(``tcp_client_socket`` / ``tls_client_socket``) pick the right adapter
via ``sys.implementation.name`` so user code never sees a runtime
check.  TLS is an injected ``ssl.SSLContext`` (not a flag); the path
is identical across runtimes — every supported board ships on-board
``ssl``.

Substrate for ``chumicro-mqtt``; downstream libs annotate against
``TCPClientSocket`` instead of importing ``socketpool`` / ``socket``
/ ``ssl`` directly.
"""

import sys

from chumicro_sockets.errors import UnsupportedSSLConfigError
from chumicro_sockets.protocol import TCPClientSocket

__all__ = [
    "TCPClientSocket",
    "UnsupportedSSLConfigError",
    "ssl_context_with_ca",
    "tcp_client_socket",
    "tcp_listening_socket",
    "tls_client_socket",
]


def _runtime_name() -> str:
    """Return ``sys.implementation.name`` (``"cpython"`` / ``"micropython"`` /
    ``"circuitpython"``).  Wrapped so tests can patch it cleanly."""
    return sys.implementation.name


def tcp_client_socket(host: str, port: int, *, radio: object | None = None) -> TCPClientSocket:
    """Open a plain TCP client connection.

    Routes to the runtime-appropriate adapter:

    * **CircuitPython** — ``socketpool.SocketPool(radio).socket(...).connect``.
      *radio* is required (typically ``wifi.radio``).
    * **MicroPython** — stdlib ``socket.socket`` + ``connect``.
      *radio* is ignored.
    * **CPython** — stdlib ``socket.create_connection``.  *radio* is ignored.

    Args:
        host: DNS name or IP literal.
        port: Remote port.
        radio: CP-only radio object.  Required on CP, ignored elsewhere.

    Returns:
        Connected :class:`TCPClientSocket`.  Already connected — callers
        do not see a separate ``connect`` step.

    Raises:
        OSError: Connection refused, DNS failure, etc.  Adapters
            normalise runtime-specific socket errors into ``OSError``.
        TypeError: CP runtime invoked without a *radio* argument.
    """
    runtime = _runtime_name()
    if runtime == "circuitpython":
        from chumicro_sockets._adapters import cp  # noqa: PLC0415 — runtime-gated import

        return cp.connect_tcp(host, port, radio=radio)
    if runtime == "micropython":
        from chumicro_sockets._adapters import mp  # noqa: PLC0415 — runtime-gated import

        return mp.connect_tcp(host, port)
    # CPython + anything else stdlib-shaped (e.g. PyPy).
    from chumicro_sockets._adapters import cpython  # noqa: PLC0415 — runtime-gated import

    return cpython.connect_tcp(host, port)


def tls_client_socket(
    host: str,
    port: int,
    *,
    context: object | None = None,
    radio: object | None = None,
) -> TCPClientSocket:
    """Open a TLS client connection.

    Routes to the runtime-appropriate adapter; *context* is honored
    on every runtime (every supported board ships on-board ``ssl``):

    * **CircuitPython** — ``context.wrap_socket(socketpool_sock,
      server_hostname=host)`` then ``connect``.  *radio* required.
    * **MicroPython** — same shape via MP's ``ssl.SSLContext``
      (mbedTLS-backed on RP2 + ESP32 from MP 1.24+).
    * **CPython** — stdlib ``ssl.SSLContext.wrap_socket``.

    *context=None* on every runtime calls the runtime's
    ``ssl.create_default_context()`` — picks up the system trust
    store, modern ciphers, hostname verification on.

    Args:
        host: DNS name or IP literal.  Used as ``server_hostname``
            for the TLS handshake (SNI + cert verification).
        port: Remote port.
        context: SSLContext to use.  ``None`` = runtime default.
            Pre-build via :func:`ssl_context_with_ca` for custom CAs.
        radio: CP-only radio object.  Required on CP, ignored elsewhere.

    Returns:
        Connected, TLS-wrapped :class:`TCPClientSocket`.

    Raises:
        OSError: Connection or handshake failure.
        TypeError: CP runtime invoked without a *radio* argument.
    """
    runtime = _runtime_name()
    if runtime == "circuitpython":
        from chumicro_sockets._adapters import cp  # noqa: PLC0415 — runtime-gated import

        return cp.connect_tls(host, port, context=context, radio=radio)
    if runtime == "micropython":
        from chumicro_sockets._adapters import mp  # noqa: PLC0415 — runtime-gated import

        return mp.connect_tls(host, port, context=context)
    from chumicro_sockets._adapters import cpython  # noqa: PLC0415 — runtime-gated import

    return cpython.connect_tls(host, port, context=context)


def tcp_listening_socket(
    host: str,
    port: int,
    *,
    backlog: int = 4,
    radio: object | None = None,
) -> object:
    """Open a non-blocking TCP listening socket.

    Routes to the runtime-appropriate adapter:

    * **CircuitPython** — ``socketpool.SocketPool(radio).socket().bind().listen()``
      (since CP 7.x).  *radio* is required (typically ``wifi.radio``).
    * **MicroPython** — ``socket.socket().bind().listen()``;
      ``setsockopt(SO_REUSEADDR, 1)`` is best-effort (some ports don't
      expose the option).  *radio* is ignored.
    * **CPython** — stdlib ``socket.socket().bind().listen()`` with
      ``SO_REUSEADDR`` set.  *radio* is ignored.

    The returned listener is in non-blocking mode — ``accept()``
    returns ``(client_socket, address)`` when a connection is ready
    or raises ``OSError(EAGAIN)`` when the queue is empty.  Substrate
    for ``chumicro-http-server``.

    Args:
        host: Address to bind to.  ``"0.0.0.0"`` accepts on every
            interface (typical for boards on a single LAN).
        port: TCP port to bind.
        backlog: SYN-queue depth for incoming connections.  4 is a
            reasonable default for a small-IoT server; raise for
            higher-volume listeners.
        radio: CP-only radio object.  Required on CP, ignored
            elsewhere.

    Returns:
        A listening socket object exposing ``accept()`` / ``close()``
        / ``setblocking()`` / ``fileno()``.

    Raises:
        OSError: Bind / listen failed (port in use, permission denied,
            etc.).
        TypeError: CP runtime invoked without a *radio* argument.
    """
    runtime = _runtime_name()
    if runtime == "circuitpython":
        from chumicro_sockets._adapters import cp  # noqa: PLC0415 — runtime-gated

        return cp.listen_tcp(host, port, backlog=backlog, radio=radio)
    if runtime == "micropython":
        from chumicro_sockets._adapters import mp  # noqa: PLC0415 — runtime-gated

        return mp.listen_tcp(host, port, backlog=backlog)
    from chumicro_sockets._adapters import cpython  # noqa: PLC0415 — runtime-gated

    return cpython.listen_tcp(host, port, backlog=backlog)


def ssl_context_with_ca(ca_pem: str | bytes) -> object:
    """Build an SSLContext that trusts the CA(s) in *ca_pem*.

    The common "default everything except the trust anchor" recipe.
    Identical shape on every runtime (every supported board ships
    on-board ``ssl``).  Returned as ``object``
    rather than ``ssl.SSLContext`` so we don't force ``import ssl``
    at module-load time on plain-TCP-only consumers.

    Args:
        ca_pem: PEM-encoded CA bundle.  ASCII / UTF-8 decodable.

    Returns:
        Configured :class:`ssl.SSLContext`.
    """
    runtime = _runtime_name()
    if runtime == "circuitpython":
        from chumicro_sockets._adapters import cp  # noqa: PLC0415 — runtime-gated import

        return cp.ssl_context_with_ca(ca_pem)
    if runtime == "micropython":
        from chumicro_sockets._adapters import mp  # noqa: PLC0415 — runtime-gated import

        return mp.ssl_context_with_ca(ca_pem)
    from chumicro_sockets._adapters import cpython  # noqa: PLC0415 — runtime-gated import

    return cpython.ssl_context_with_ca(ca_pem)
