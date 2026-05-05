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
    """Stand-in for ``setblocking`` / ``settimeout`` / ``fileno`` on
    sockets that don't expose them.

    Verified live on MP 1.28.0 (Pi Pico W RP2 + Lolin S2 ESP32-S2):
    both plain ``socket`` and mbedTLS ``SSLSocket`` *do* expose
    ``setblocking`` so the no-op fallback is mostly defensive for
    older firmwares / non-mbedTLS ports.  ``settimeout`` is genuinely
    absent on SSLSocket on those boards (the call surface stops at
    ``setblocking``); ``fileno`` is absent on RP2's plain socket.
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
        # Soft-forward setblocking / settimeout / fileno.  Live-board
        # findings on MP 1.28.0 (Pi Pico W RP2, Lolin S2 ESP32-S2):
        # SSLSocket exposes ``setblocking`` but not ``settimeout``;
        # plain socket on RP2 has no ``fileno``.  Fall back to no-op
        # / ``-1`` stubs so downstream code doesn't trip at
        # construction time on the cases where a method is absent.
        self.setblocking = getattr(sock, "setblocking", _no_op)
        self.settimeout = getattr(sock, "settimeout", _no_op)
        forwarded_fileno = getattr(sock, "fileno", None)
        self.fileno = forwarded_fileno if forwarded_fileno is not None else _no_fileno

    def recv_into(self, buffer, nbytes=0):
        """Polyfill ``recv_into`` via MP's ``recv``.

        ``recv(nbytes)`` returns up to *nbytes* bytes; we copy the
        result into *buffer* and return the count.  Empty-bytes
        return (``b""``) on a clean peer close → returns 0, same
        contract as stdlib.

        MP-specific contract divergence (verified live on Pi Pico W
        RP2 + Lolin S2 ESP32-S2 with MP 1.28.0):

        * Plain TCP non-blocking ``recv`` with no data → raises
          ``OSError(11)`` (EAGAIN).
        * mbedTLS ``SSLSocket`` non-blocking ``recv`` with no data
          → returns ``None`` (mbedTLS ``WANT_READ`` /``WANT_WRITE``
          maps to ``MP_EWOULDBLOCK`` internally, but the Python-level
          surface for SSLSocket returns ``None`` rather than raising).

        We **raise** ``OSError(11)`` on ``None`` so the protocol
        contract — "EAGAIN on no data, 0 on clean peer close" —
        holds across plain TCP and TLS uniformly.  Callers like
        ``chumicro-requests`` that need to distinguish "no data
        this tick" from "peer closed mid-response" depend on this:
        without it the HTTP parser fails length-known responses
        on MP TLS the moment a recv races ahead of the peer's
        send.  See `chumicro-requests` slice 3c for the surfacing
        bug.  ``chumicro-mqtt``'s RX loop already handled both
        EAGAIN and 0 with a ``break``, so it sees no behavior
        change here.
        """
        size = nbytes if nbytes > 0 else len(buffer)
        data = self._sock.recv(size)
        if data is None:
            raise OSError(11, "would block")  # MP TLS WANT_READ.
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

    Non-blocking note: callers that need a non-blocking TLS socket
    (e.g. ``chumicro-mqtt``) call ``setblocking(False)`` on the
    returned wrapper *after* the synchronous handshake completes
    inside ``wrap_socket``.  Verified live on MP 1.28.0: both the
    Pi Pico W RP2 and Lolin S2 ESP32-S2 mbedTLS SSLSocket honor
    ``setblocking``.  The wrapper's ``recv_into`` polyfill handles
    the MP-TLS-specific contract divergence where non-blocking
    ``recv`` returns ``None`` (rather than raising EAGAIN like
    plain TCP); see :class:`_MpSocketWrapper.recv_into`.
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


def udp_socket(  # pragma: no cover - device only
    *,
    bind_host="0.0.0.0",
    bind_port=0,
    broadcast=False,
):
    """Open a UDP socket on MicroPython, bound to (bind_host, bind_port).

    MP exposes ``socket.socket(AF_INET, SOCK_DGRAM)`` on every supported
    port (rp2 + esp32, MP 1.24+).  ``recvfrom`` is universal; ``recvfrom_into``
    is patchy (rp2 has it, esp32 may lack it depending on build), so the
    wrapper polyfills via ``recvfrom`` + buffer copy.

    ``SO_BROADCAST`` is best-effort — failures are swallowed so older
    ports without the option don't break the socket factory.
    """
    import socket  # noqa: PLC0415 — runtime-gated; lazy so CP can stage this file

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    if broadcast:
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        except OSError:
            # Some MP ports don't expose SO_BROADCAST; non-fatal.
            pass
    address_info = socket.getaddrinfo(bind_host, bind_port)[0]
    sock.bind(address_info[-1])
    return _MpUDPWrapper(sock)


class _MpUDPWrapper:  # pragma: no cover - device only
    """Adapts an MP UDP socket to the chumicro_sockets UDP protocol.

    MP's UDP socket exposes ``sendto((data, address))`` as
    ``sendto(data, address_tuple)`` and ``recvfrom(nbytes)`` returning
    ``(data, address)``.  We normalise both into the separated-arg
    public surface and polyfill ``recvfrom_into`` via ``recvfrom`` +
    bytearray copy (matches the TCP ``_MpSocketWrapper.recv_into``
    polyfill rationale: small one-shot allocation, no concurrent
    network in flight).
    """

    def __init__(self, sock):
        self._sock = sock
        self.close = sock.close
        self.setblocking = getattr(sock, "setblocking", _no_op)
        self.settimeout = getattr(sock, "settimeout", _no_op)
        forwarded_fileno = getattr(sock, "fileno", None)
        self.fileno = forwarded_fileno if forwarded_fileno is not None else _no_fileno
        forwarded_getsockname = getattr(sock, "getsockname", None)
        if forwarded_getsockname is not None:
            self.getsockname = forwarded_getsockname
        else:
            # Some MP ports omit getsockname; report a placeholder so
            # downstream code doesn't trip on an absent attribute.
            self.getsockname = lambda: ("0.0.0.0", 0)

    def sendto(self, data, host, port):
        # MP's UDP ``sendto`` does not auto-resolve hostnames — passing
        # ``("pool.ntp.org", 123)`` raises ``ValueError: invalid
        # arguments`` because MP expects a packed sockaddr.  Route
        # through ``getaddrinfo`` (which CircuitPython and CPython
        # already do internally) so the public API is hostname-clean
        # across every runtime.  Numeric-IP callers pay an O(1)
        # short-circuit lookup; hostname callers pay one DNS round-trip
        # per ``sendto`` — acceptable for chumicro-ntp-shaped traffic
        # (one send per query).  Callers in tighter loops should
        # pre-resolve and cache the IP themselves.
        import socket  # noqa: PLC0415 — runtime-gated; lazy so CP can stage this file

        address_info = socket.getaddrinfo(host, port)[0]
        return self._sock.sendto(data, address_info[-1])

    def recvfrom_into(self, buffer, nbytes=0):
        size = nbytes if nbytes > 0 else len(buffer)
        result = self._sock.recvfrom(size)
        # MP returns (data, address); some ports may return None on
        # would-block instead of raising — match the TCP wrapper's
        # contract by raising EAGAIN explicitly.
        if result is None:
            raise OSError(11, "would block")
        data, address = result
        copied = len(data)
        if copied:
            buffer[:copied] = data
        return copied, address


def listen_tcp(host, port, *, backlog=4):  # pragma: no cover - device only
    """Open a non-blocking TCP listening socket on MicroPython.

    Wraps the result so ``accept()`` returns a ``(_MpSocketWrapper,
    address)`` tuple — the new connection satisfies our
    :class:`TCPClientSocket` protocol.

    ``SO_REUSEADDR`` is set when the platform supports it (rp2 + esp32
    do); failures are swallowed so older ports without the option
    don't break the listener.
    """
    import socket  # noqa: PLC0415 — runtime-gated

    address_info = socket.getaddrinfo(host, port)[0]
    listener = socket.socket(address_info[0], address_info[1])
    try:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    except OSError:
        # Some MP ports don't expose SO_REUSEADDR; non-fatal.
        pass
    listener.bind(address_info[-1])
    listener.listen(backlog)
    listener.setblocking(False)
    return _MpListeningSocketWrapper(listener)


class _MpListeningSocketWrapper:  # pragma: no cover - device only
    """Adapts an MP listening socket so ``accept()`` returns a
    wrapped client socket (matching our protocol)."""

    def __init__(self, sock):
        self._sock = sock
        self.close = sock.close
        forwarded_fileno = getattr(sock, "fileno", None)
        self.fileno = forwarded_fileno if forwarded_fileno is not None else _no_fileno

    def accept(self):
        """Accept a pending connection.  Raises ``OSError(EAGAIN)`` when
        none is queued (matches the cross-runtime contract)."""
        new_sock, address = self._sock.accept()
        return _MpSocketWrapper(new_sock), address

    def setblocking(self, flag):
        self._sock.setblocking(flag)


def ssl_context_with_cert_and_key(cert_pem, key_pem):  # pragma: no cover - device only
    """Build an MP server-side SSLContext from in-memory cert + key.

    MP's `ssl.SSLContext.load_cert_chain` accepts cert + key as
    bytes (rp2 / esp32 builds since MP 1.24+).  We pass the PEM text
    through directly — unlike `load_verify_locations` which on rp2
    needs DER (no MBEDTLS_PEM_PARSE_C), `load_cert_chain` parses PEM
    on every supported MP build because the server-side path enables
    the PEM parser.

    Returned context targets `PROTOCOL_TLS_SERVER`.
    """
    import ssl  # noqa: PLC0415 — runtime-gated

    if isinstance(cert_pem, str):
        cert_pem = cert_pem.encode("ascii")
    if isinstance(key_pem, str):
        key_pem = key_pem.encode("ascii")
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert_pem, key_pem)
    return context


def listen_tls(host, port, *, context, backlog=4):  # pragma: no cover - device only
    """Open an MP TLS listening socket.

    The TLS handshake happens synchronously inside `accept()` —
    MP's `wrap_socket(server_side=True)` blocks until the handshake
    completes.  HttpServer accepts that as the per-tick latency
    cost.
    """
    raw_listener = listen_tcp(host, port, backlog=backlog)
    return _MpTLSListenerWrapper(raw_listener, context)


class _MpTLSListenerWrapper:  # pragma: no cover - device only
    """Wraps an MP listener so accept() yields TLS-wrapped sockets."""

    def __init__(self, raw_listener, context):
        self._raw = raw_listener
        self._context = context

    def accept(self):
        new_wrapper, address = self._raw.accept()
        # Pull the underlying MP socket out of the wrapper so we
        # can wrap it directly with TLS — the handshake needs the
        # raw socket, not our `_MpSocketWrapper` polyfill.
        underlying = new_wrapper._sock
        underlying.setblocking(True)
        try:
            tls_sock = self._context.wrap_socket(underlying, server_side=True)
        except Exception:
            underlying.close()
            raise
        # SSLSocket on MP supports setblocking on rp2 + esp32 (verified
        # MP 1.28.0); falls back to no-op on older ports via the
        # existing _MpSocketWrapper.
        return _MpSocketWrapper(tls_sock), address

    def close(self):
        self._raw.close()

    def setblocking(self, flag):
        self._raw.setblocking(flag)

    def fileno(self):
        return self._raw.fileno() if hasattr(self._raw, "fileno") else _no_fileno()


def ssl_context_with_ca(ca_pem):  # pragma: no cover - device only
    """Build an MP ``ssl.SSLContext`` that trusts only *ca_pem*.

    Accepts a **PEM** input (the standard ``-----BEGIN CERTIFICATE-----``
    block that ``openssl`` produces by default).  Converts to DER
    internally before passing to ``load_verify_locations`` so it
    works on every MP port — including the rp2 (Pi Pico W) build
    that ships mbedTLS *without* ``MBEDTLS_PEM_PARSE_C`` to save flash.

    Multi-cert PEM bundles (multiple ``-----BEGIN CERTIFICATE-----``
    blocks back-to-back) are supported: each block is converted to
    DER independently and the DERs are concatenated.  mbedTLS's
    ``mbedtls_x509_crt_parse`` walks a buffer of sequential DER
    certs natively.

    Why the conversion: live-tested on MP 1.28.0 (2026-04-26) by
    feeding ``load_verify_locations`` the same self-signed CA five
    different ways:

    * Pi Pico W RP2 — every PEM variant raises ``ValueError('invalid
      cert')``; only DER (binary, no PEM markers) loads.
    * Lolin S2 ESP32-S2 — PEM (string or bytes, with or without
      trailing newline, LF or CRLF) loads.  DER also loads.

    The split is build-config: ESP-IDF's mbedTLS is built with
    ``MBEDTLS_PEM_PARSE_C``; rp2's port-bundled mbedTLS is not
    (the symbol isn't defined in
    ``ports/rp2/mbedtls/mbedtls_config_port.h`` or the common
    config it pulls in).  DER is the lowest-common-denominator
    that works everywhere.

    The returned context defaults to ``verify_mode = CERT_REQUIRED``
    — loading a CA only makes sense when you intend to verify
    against it.  Override on the returned context if you need a
    different mode for a specific test.

    Args:
        ca_pem: PEM-encoded CA bundle as bytes or str.  ASCII /
            UTF-8 decodable.  Single cert or multi-cert bundle.
    """
    import ssl  # noqa: PLC0415 — MP-only import

    if isinstance(ca_pem, str):
        ca_pem = ca_pem.encode("ascii")
    der = _pem_to_der(ca_pem)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.load_verify_locations(cadata=der)
    context.verify_mode = ssl.CERT_REQUIRED
    return context


def _pem_to_der(ca_pem):  # pragma: no cover - device only
    """Convert a PEM bundle (one or more certs) to concatenated DER bytes.

    Walks line-by-line, accumulating base64 between matched
    ``-----BEGIN CERTIFICATE-----`` / ``-----END CERTIFICATE-----``
    pairs.  Each pair's body is base64-decoded independently; the
    resulting DER blocks are concatenated.  Tolerates LF or CRLF
    line endings, blank lines, leading / trailing whitespace.
    """
    import binascii  # noqa: PLC0415 — MP-only import

    der_parts = []
    base64_lines = []
    in_cert = False
    for raw_line in ca_pem.split(b"\n"):
        line = raw_line.strip()
        if line == b"-----BEGIN CERTIFICATE-----":
            in_cert = True
            base64_lines = []
            continue
        if line == b"-----END CERTIFICATE-----":
            if in_cert and base64_lines:
                der_parts.append(binascii.a2b_base64(b"".join(base64_lines)))
            in_cert = False
            base64_lines = []
            continue
        if in_cert and line:
            base64_lines.append(line)
    return b"".join(der_parts)
