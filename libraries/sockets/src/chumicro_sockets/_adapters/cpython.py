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


def udp_socket(*, bind_host="0.0.0.0", bind_port=0, broadcast=False):
    """Open a UDP socket on CPython, bound to (bind_host, bind_port).

    Returns a :class:`_CPythonUDPWrapper` so the public ``sendto(data,
    host, port)`` separated-arg shape is honored (stdlib expects a
    ``(host, port)`` tuple).
    """
    import socket  # noqa: PLC0415 — runtime-gated

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    if broadcast:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.bind((bind_host, bind_port))
    return _CPythonUDPWrapper(sock)


class _CPythonUDPWrapper:
    """Adapts a CPython ``socket.socket`` to the chumicro_sockets UDP protocol.

    Normalizes ``sendto`` to the separated ``(data, host, port)``
    signature and ``recvfrom_into`` to the ``(nbytes, (host, port))``
    return tuple.
    """

    def __init__(self, sock):
        self._sock = sock
        self.close = sock.close
        self.setblocking = sock.setblocking
        self.settimeout = sock.settimeout
        self.fileno = sock.fileno
        self.getsockname = sock.getsockname

    def sendto(self, data, host, port):
        return self._sock.sendto(data, (host, port))

    def recvfrom_into(self, buffer, nbytes=0):
        size = nbytes if nbytes > 0 else len(buffer)
        view = memoryview(buffer)[:size]
        nbytes_received, address = self._sock.recvfrom_into(view, size)
        return nbytes_received, address


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
    if isinstance(ca_pem, str):
        context.load_verify_locations(cadata=ca_pem)
    else:
        raw = bytes(ca_pem)
        if b"-----BEGIN CERTIFICATE-----" in raw:
            # PEM bytes — stdlib wants ``cadata`` as str for PEM.
            context.load_verify_locations(cadata=raw.decode("ascii"))
        elif raw[:1] == b"\x30":
            # DER (ASN.1 SEQUENCE) — stdlib accepts bytes-like cadata
            # as DER directly.
            context.load_verify_locations(cadata=raw)
        else:
            raise ValueError(
                "ssl_context_with_ca expects PEM "
                "(-----BEGIN CERTIFICATE-----) or DER (ASN.1 SEQUENCE, "
                "first byte 0x30) — got neither",
            )
    return context


def ssl_context_no_verify():
    """Return a CPython ``ssl.SSLContext`` that **skips** verification.

    Explicit opt-out for callers that intentionally don't want to
    validate the peer.  Named so code reviewers can grep for it —
    ``tls_client_socket(host, port, context=ssl_context_no_verify())``
    shouts what it does.

    Inverts both of ``ssl.create_default_context``'s secure defaults:
    ``check_hostname = False`` (must come first — stdlib refuses to
    set ``verify_mode = CERT_NONE`` while ``check_hostname`` is true)
    and ``verify_mode = CERT_NONE``.
    """
    import ssl  # noqa: PLC0415 — runtime-gated

    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    return context
