"""CPython adapter — stdlib ``socket`` + ``ssl``.

Used:

* on CPython directly (host-side tests, sim runs, downstream libs
  imported on a laptop without a board);
* as the test substrate for ``FakeSocket`` conformance — passing
  tests here prove the contract every other adapter implements.

``socket.create_connection`` does the dial-and-connect and raises
:class:`OSError` on failure.  TLS uses ``ssl.SSLContext.wrap_socket``;
``context=None`` means ``ssl.create_default_context()``.

Imports happen INSIDE the functions: CP RAM-mode bootstrap stages
every adapter file and a top-level ``import socket`` would fail on
CP.  Lazy imports keep this adapter staged-but-quiet on CP.
"""

#: Source bundle only; never lands on a device.
__chumicro_runtimes__ = ("cpython",)


def connect_tcp(host, port):
    """Open a plain TCP connection.

    Returns a real :class:`socket.socket` — already satisfies
    :class:`TCPClientSocket` structurally (stdlib's surface is a
    superset of our protocol).
    """
    import socket  # noqa: PLC0415 — runtime-gated; lazy so CP can stage this file

    return socket.create_connection((host, port))


def connect_tls(host, port, *, context=None):
    """Open a TLS connection.

    *context=None* uses :func:`ssl.create_default_context` — system
    default CA bundle, hostname check enabled, modern cipher defaults.
    Pass a pre-configured context for custom CAs / mTLS / pinned
    cipher suites.
    """
    import socket  # noqa: PLC0415 — runtime-gated
    import ssl  # noqa: PLC0415 — runtime-gated

    raw = socket.create_connection((host, port))
    resolved_context = (
        context if context is not None else ssl.create_default_context()
    )
    return resolved_context.wrap_socket(raw, server_hostname=host)


def ssl_context_with_ca(ca_pem):
    """Build an SSLContext that trusts only the CA(s) in *ca_pem*.

    Uses :meth:`ssl.SSLContext.load_verify_locations` with the PEM
    bytes — stdlib accepts a string or bytes via ``cadata``, so we
    pass either form through unchanged.  The context still enforces
    hostname verification and modern cipher defaults; only the trust
    anchor is replaced.
    """
    import ssl  # noqa: PLC0415 — runtime-gated

    context = ssl.create_default_context()
    if isinstance(ca_pem, (bytes, bytearray)):
        ca_pem = bytes(ca_pem).decode("ascii")
    context.load_verify_locations(cadata=ca_pem)
    return context
