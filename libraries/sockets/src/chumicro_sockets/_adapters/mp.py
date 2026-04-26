"""MicroPython adapter — stdlib ``socket`` + ``ssl`` (mbedTLS-backed).

One MP adapter covers every supported port (MP 1.26+ ships
``MICROPY_SSL_MBEDTLS=1`` on both ESP32 and RP2; the "no TLS on Pico
W" folklore is pre-mbedTLS).

Imports of ``socket`` / ``ssl`` happen INSIDE the functions: CP's
RAM-mode bootstrap stages every deploy file and imports it, and a
top-level ``import socket`` would fail on CP (no ``socket`` module).
Lazy imports keep this adapter staged-but-quiet on CP.

``recv_into`` polyfill: MP's stream-backed socket exposes ``recv()``
but not ``recv_into()``; :class:`_MpSocketWrapper` adapts via
``recv() + memoryview-copy`` so downstream code sees the unified
protocol.

TLS: always pass *host* as ``server_hostname`` (SNI-less verification
breaks against modern brokers).
"""

__chumicro_runtimes__ = ("micropython",)


def _no_fileno():
    """Stand-in for missing ``socket.fileno`` on some MP ports.

    Returns -1 — the "no real fd" convention chumicro-sockets uses
    so callers can detect "this socket can't be poll()'d" without a
    runtime check on every callsite.
    """
    return -1


def _no_op(*_args, **_kwargs):
    """Stand-in for missing ``setblocking`` / ``settimeout`` on SSLSocket.

    Some MP TLS implementations (live-board: Lolin S2 ESP32) wrap
    the underlying socket and drop these methods.  The TLS layer's
    own blocking mode is what's actually consulted on send/recv, so
    the absence is benign — caller's setblocking(False) / settimeout
    request is a no-op rather than a hard error.
    """
    return None


class _MpSocketWrapper:
    """Adapts an MP stdlib socket to the chumicro_sockets protocol.

    MP's socket lacks ``recv_into`` on the supported boards (1.26+
    rp2 / esp32 ports), so the wrapper synthesizes it from
    ``recv(nbytes) + buffer[:n] = data``.  Every other protocol
    method is a direct attribute forward; the wrapper is a thin
    object whose attribute resolution costs ~one dict lookup per
    call site.
    """

    def __init__(self, sock):
        self._sock = sock
        # Forward the operations MP's socket supports natively so
        # downstream callers don't pay a Python-level shim round-trip
        # on every call.  ``send`` and ``close`` are required — every
        # socket-shaped object exposes them.
        self.send = sock.send
        self.close = sock.close
        # Soft-forward setblocking / settimeout / fileno: MP's
        # SSLSocket wrapper drops some of them on certain ports
        # (live-board run on Lolin S2 ESP32 saw
        # ``AttributeError("'SSLSocket' object has no attribute 'settimeout'")``;
        # Pi Pico W RP2 has no ``fileno``).  Fall back to no-op /
        # ``-1`` stubs so downstream code doesn't trip at
        # construction time — would-block semantics still hold via
        # the underlying TLS layer's internal blocking mode.
        self.setblocking = getattr(sock, "setblocking", _no_op)
        self.settimeout = getattr(sock, "settimeout", _no_op)
        forwarded_fileno = getattr(sock, "fileno", None)
        self.fileno = forwarded_fileno if forwarded_fileno is not None else _no_fileno

    def recv_into(self, buffer, nbytes=0):
        """Polyfill ``recv_into`` via MP's ``recv``.

        ``recv(nbytes)`` returns up to *nbytes* bytes; we copy the
        result into *buffer* and return the count.  Empty-bytes
        return on a clean peer close — same contract as stdlib.
        """
        size = nbytes if nbytes > 0 else len(buffer)
        data = self._sock.recv(size)
        copied = len(data)
        if copied:
            buffer[:copied] = data
        return copied


def connect_tcp(host, port):  # pragma: no cover - device only
    """Open a plain TCP connection on MicroPython.

    Uses ``socket.getaddrinfo`` + ``socket.socket`` + ``connect`` —
    MP's ``create_connection`` shim is missing on some builds, so
    we do the dance explicitly.
    """
    import socket  # noqa: PLC0415 — MP-only import; staged-but-not-imported on CP

    address_info = socket.getaddrinfo(host, port)[0]
    sock = socket.socket(address_info[0], address_info[1])
    sock.connect(address_info[-1])
    return _MpSocketWrapper(sock)


def connect_tls(host, port, *, context=None):  # pragma: no cover - device only
    """Open a TLS connection on MicroPython.

    *context* is an MP ``ssl.SSLContext`` (or ``None`` for the
    default).  When ``None``, ``ssl.wrap_socket`` is called with
    ``server_hostname=host`` so the TLS handshake validates the
    cert chain against the system trust store.

    Older MP builds expose ``ssl.wrap_socket`` as a free function
    rather than a context method — this adapter calls the free
    function so it works on both shapes.
    """
    import socket  # noqa: PLC0415 — MP-only import; staged-but-not-imported on CP
    import ssl  # noqa: PLC0415 — MP-only import

    address_info = socket.getaddrinfo(host, port)[0]
    sock = socket.socket(address_info[0], address_info[1])
    sock.connect(address_info[-1])
    if context is None:
        wrapped = ssl.wrap_socket(sock, server_hostname=host)
    else:
        wrapped = context.wrap_socket(sock, server_hostname=host)
    return _MpSocketWrapper(wrapped)


def ssl_context_with_ca(ca_pem):  # pragma: no cover - device only
    """Build an MP ``ssl.SSLContext`` that trusts only *ca_pem*.

    MP's ``ssl.SSLContext`` accepts ``load_verify_locations`` with
    ``cadata`` (string).  Modern MP builds (1.24+) implement the
    same call shape as CPython, so the helper is a near-clone of
    the CPython one.
    """
    import ssl  # noqa: PLC0415 — MP-only import

    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.load_verify_locations(cadata=ca_pem.decode("ascii"))
    return context
