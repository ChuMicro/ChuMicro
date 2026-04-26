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

Decision 0031 specifies the architecture: per-runtime adapters under
``_adapters/``, two sibling factories (``tcp_client_socket`` and
``tls_client_socket``), and TLS as a proper injected dependency
rather than a flag.  The factories pick the right adapter via
``sys.implementation.name`` so user code never sees a runtime check.

This package is the substrate for ``chumicro-mqtt`` and a future
``chumicro-requests`` — neither imports ``socketpool``, ``socket``,
or ``ssl`` directly.

The TLS path looks identical across runtimes (Decision 0015 minimum
supported board class — Pi Pico W, ESP32-S2/S3, ESP32-S3 Feather —
all ship the on-board ``ssl`` module on current LTS firmware):
``tls_client_socket`` accepts an :class:`ssl.SSLContext` (or
``None`` for the runtime default) on every runtime.
"""

import sys

from chumicro_sockets.errors import UnsupportedSSLConfigError
from chumicro_sockets.protocol import TCPClientSocket

__all__ = [
    "TCPClientSocket",
    "UnsupportedSSLConfigError",
    "ssl_context_with_ca",
    "tcp_client_socket",
    "tls_client_socket",
]


def _runtime_name() -> str:
    """Return ``sys.implementation.name`` (``"cpython"`` / ``"micropython"`` /
    ``"circuitpython"``).  Wrapped so tests can patch it cleanly."""
    return sys.implementation.name


def tcp_client_socket(host, port, *, radio=None):
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


def tls_client_socket(host, port, *, context=None, radio=None):
    """Open a TLS client connection.

    Routes to the runtime-appropriate adapter; *context* is honored
    on every runtime (Decision 0015 supported boards all ship the
    on-board ``ssl`` module):

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


def ssl_context_with_ca(ca_pem):
    """Build an SSLContext that trusts the CA(s) in *ca_pem*.

    The common "default everything except the trust anchor" recipe.
    Identical shape on every runtime (Decision 0015 supported boards
    all ship the on-board ``ssl`` module).

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
