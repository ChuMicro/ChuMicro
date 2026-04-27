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


def listen_tcp(host, port, *, backlog=4):
    """Open a non-blocking TCP listening socket.

    Returns a real :class:`socket.socket` set to non-blocking mode and
    bound + listening on (*host*, *port*).  Already satisfies the
    ``ListeningSocket`` structural protocol — :meth:`socket.accept`
    returns ``(socket, address)`` and raises ``OSError(EAGAIN)`` when
    no connection is queued.

    ``SO_REUSEADDR`` is set so a quick restart of the server doesn't
    trip ``OSError(EADDRINUSE)`` on the rebind.
    """
    import socket  # noqa: PLC0415 — runtime-gated

    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind((host, port))
    listener.listen(backlog)
    listener.setblocking(False)
    return listener


def ssl_context_with_cert_and_key(cert_pem, key_pem):
    """Build a server-side SSLContext that presents *cert_pem* signed by *key_pem*.

    Used by `tls_listening_socket` on the server side.  Mirrors the
    client-side `ssl_context_with_ca` shape but loads a *cert chain*
    + *private key* via `SSLContext.load_cert_chain` (rather than a
    *trust store*).  The context is suitable for `wrap_socket(...,
    server_side=True)` calls.

    *cert_pem* and *key_pem* are PEM-encoded bytes / str.  CPython's
    `load_cert_chain` accepts file paths only (not in-memory bytes),
    so we write them to a temporary file and load from there.
    """
    import ssl  # noqa: PLC0415 — runtime-gated
    import tempfile  # noqa: PLC0415 — runtime-gated

    if isinstance(cert_pem, (bytes, bytearray)):
        cert_pem_text = bytes(cert_pem).decode("ascii")
    else:
        cert_pem_text = cert_pem
    if isinstance(key_pem, (bytes, bytearray)):
        key_pem_text = bytes(key_pem).decode("ascii")
    else:
        key_pem_text = key_pem
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".cert.pem", delete=False,
    ) as cert_handle:
        cert_handle.write(cert_pem_text)
        cert_path = cert_handle.name
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".key.pem", delete=False,
    ) as key_handle:
        key_handle.write(key_pem_text)
        key_path = key_handle.name
    context.load_cert_chain(certfile=cert_path, keyfile=key_path)
    return context


def listen_tls(host, port, *, context, backlog=4):
    """Open a non-blocking TLS listening socket on CPython.

    Returns a wrapper whose `accept()` returns a `(tls_wrapped_client,
    address)` tuple — the TLS handshake happens synchronously inside
    `accept()`.  Per-runtime contract documented in the public
    `tls_listening_socket` factory.
    """
    raw_listener = listen_tcp(host, port, backlog=backlog)
    return _CPythonTLSListenerWrapper(raw_listener, context)


class _CPythonTLSListenerWrapper:
    """Wraps a raw CPython listener so accept() yields TLS sockets.

    The TLS handshake runs inside `accept()` after the TCP `accept()`
    returns the new client.  On a non-blocking listener the underlying
    `accept()` raises `BlockingIOError` when no client is queued; we
    propagate that as `OSError(EAGAIN)`.
    """

    def __init__(self, raw_listener, context):
        self._raw = raw_listener
        self._context = context

    def accept(self):  # pragma: no cover - exercised by slice 7t live test
        client_raw, address = self._raw.accept()
        # `wrap_socket(..., server_side=True)` performs the TLS
        # handshake synchronously.  Set the underlying socket to
        # blocking for the handshake (mbedTLS doesn't support
        # async handshake on the server side cleanly), then back
        # to non-blocking for the application traffic.
        client_raw.setblocking(True)
        try:
            wrapped = self._context.wrap_socket(client_raw, server_side=True)
        except Exception:
            client_raw.close()
            raise
        wrapped.setblocking(False)
        return wrapped, address

    def close(self):
        self._raw.close()

    def setblocking(self, flag):  # pragma: no cover - listener already non-blocking
        self._raw.setblocking(flag)

    def fileno(self):  # pragma: no cover - poll integration optional
        return self._raw.fileno()

    def getsockname(self):  # pragma: no cover - inspection-only
        return self._raw.getsockname()


def ssl_context_with_ca(ca_pem):
    """Build an SSLContext that trusts only the CA(s) in *ca_pem*.

    Uses :meth:`ssl.SSLContext.load_verify_locations` with the PEM
    bytes — stdlib accepts a string or bytes via ``cadata``, so we
    pass either form through unchanged.  The context inherits
    ``ssl.create_default_context``'s ``CERT_REQUIRED`` +
    ``check_hostname=True`` defaults; only the trust anchor is
    replaced.  Override on the returned context if needed.
    """
    import ssl  # noqa: PLC0415 — runtime-gated

    context = ssl.create_default_context()
    if isinstance(ca_pem, (bytes, bytearray)):
        ca_pem = bytes(ca_pem).decode("ascii")
    context.load_verify_locations(cadata=ca_pem)
    return context
