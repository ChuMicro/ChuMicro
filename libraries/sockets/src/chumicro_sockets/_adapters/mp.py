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

import gc

from chumicro_sockets._connector import (
    _TERMINAL,
    STATE_AWAITING_DNS,
    STATE_AWAITING_TCP,
    STATE_AWAITING_TLS,
    STATE_READY,
    SocketConnector,
)


def _no_op(*_args, **_kwargs):
    """Stand-in no-op for ``settimeout`` on mbedTLS ``SSLSocket``.

    MP's mbedTLS ``SSLSocket`` call surface stops at ``setblocking``
    — it does not expose ``settimeout``.  Installed via
    ``getattr(sock, "settimeout", _no_op)`` in
    :class:`_MpSocketWrapper` so callers see the unified TCP
    protocol surface across plain and TLS-wrapped sockets.
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
        # on every call.  ``send`` / ``close`` / ``setblocking`` are
        # universal across plain and TLS-wrapped MP sockets.
        self.send = sock.send
        self.close = sock.close
        self.setblocking = sock.setblocking
        # mbedTLS ``SSLSocket`` does not expose ``settimeout`` — falls
        # back to a no-op so the wrapper surface stays uniform for
        # both plain TCP and TLS sockets.
        self.settimeout = getattr(sock, "settimeout", _no_op)

    def recv_into(self, buffer, nbytes=0):
        """Polyfill ``recv_into`` via MP's ``recv``.

        ``recv(nbytes)`` returns up to *nbytes* bytes; we copy the
        result into *buffer* and return the count.  ``recv`` returns
        ``b""`` on a clean peer close, and the polyfill translates
        that to ``0`` — the stdlib contract.

        MP-specific contract divergence:

        * Plain TCP non-blocking ``recv`` with no data raises
          ``OSError(errno.EAGAIN)``.
        * mbedTLS ``SSLSocket`` non-blocking ``recv`` with no data
          returns ``None`` instead (mbedTLS ``WANT_READ`` /
          ``WANT_WRITE`` maps to ``MP_EWOULDBLOCK`` internally, but
          the Python-level surface for SSLSocket returns ``None``
          rather than raising).

        We **raise** ``OSError(errno.EAGAIN)`` on ``None`` so the
        protocol contract — "EAGAIN on no data, 0 on clean peer
        close" — holds across plain TCP and TLS uniformly.  Without
        it, a length-known TCP-style read on MP TLS cannot tell
        "no data this tick" apart from "peer closed mid-response"
        the moment a recv races ahead of the peer's send.
        """
        size = nbytes if nbytes > 0 else len(buffer)
        import errno  # noqa: PLC0415 — MP-only; lazy per file convention.

        data = self._sock.recv(size)
        if data is None:
            # MP TLS WANT_READ surfaces as recv() returning None; raise
            # the would-block errno so the recv-loop contract holds
            # against plain TCP and TLS uniformly.
            raise OSError(errno.EAGAIN, "would block")
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

    *context* is an MP ``ssl.SSLContext`` or ``None``.

    When ``context`` is ``None``, the TLS handshake validates the
    server cert against the library-shipped CA bundle in
    :mod:`chumicro_sockets._ca_bundle` — loaded lazily and cached at
    module level via :func:`_default_context`.  Override the trust set
    at runtime with :func:`set_default_ca_bundle` (called transparently
    by ``chumicro_sockets.set_default_ca_bundle``).  For explicit
    no-verification (dev against self-signed brokers, captive-portal
    probes), pass ``context=ssl_context_no_verify()`` — opt-out is
    named so a code reviewer can grep for it.

    Non-blocking note: callers that need a non-blocking TLS socket
    call ``setblocking(False)`` on the returned wrapper *after* the
    synchronous handshake completes inside ``wrap_socket``.  Both
    the MP rp2 and ESP32 mbedTLS SSLSocket honor ``setblocking``
    post-handshake.  The wrapper's ``recv_into`` polyfill handles
    the MP-TLS-specific contract divergence where non-blocking
    ``recv`` returns ``None`` (rather than raising EAGAIN like
    plain TCP); see :class:`_MpSocketWrapper.recv_into`.
    """
    import socket  # noqa: PLC0415 — MP-only import; staged-but-not-imported on CP

    address_info = socket.getaddrinfo(host, port)[0]
    sock = socket.socket(address_info[0], address_info[1])
    sock.connect(address_info[-1])
    context = _resolve_default_context(context)
    wrapped = context.wrap_socket(sock, server_hostname=host)
    return _MpSocketWrapper(wrapped)


def _resolve_default_context(context):  # pragma: no cover - device only
    """Return *context* unchanged, or load MP's default context if ``None``.

    The default trust set is the chumicro-shipped DER bundle in
    :mod:`chumicro_sockets._ca_bundle`, parsed once and cached on
    :func:`_default_context`.  Override it at runtime via
    :func:`set_default_ca_bundle`.
    """
    if context is not None:
        return context
    return _default_context()


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
    ``(data, address)``.  We normalize both into the separated-arg
    public surface and polyfill ``recvfrom_into`` via ``recvfrom`` +
    bytearray copy (matches the TCP ``_MpSocketWrapper.recv_into``
    polyfill rationale: small one-shot allocation, no concurrent
    network in flight).
    """

    def __init__(self, sock):
        self._sock = sock
        self.close = sock.close
        self.setblocking = sock.setblocking
        self.settimeout = sock.settimeout
        self.getsockname = sock.getsockname

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
        import errno  # noqa: PLC0415 — MP-only; lazy per file convention.

        size = nbytes if nbytes > 0 else len(buffer)
        result = self._sock.recvfrom(size)
        # MP returns (data, address); some ports may return None on
        # would-block instead of raising — match the TCP wrapper's
        # contract by raising EAGAIN explicitly.
        if result is None:
            raise OSError(errno.EAGAIN, "would block")
        data, address = result
        copied = len(data)
        if copied:
            buffer[:copied] = data
        return copied, address


def listen_tcp(host, port, *, backlog=4):  # pragma: no cover - device only
    """Open a non-blocking TCP listening socket on MicroPython.

    Wraps the result so ``accept()`` returns a ``(_MpSocketWrapper,
    address)`` tuple — the new connection exposes the cross-runtime
    TCP surface (``send`` / ``recv_into`` / ``close`` /
    ``setblocking`` / ``settimeout``).

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

    def accept(self):
        """Accept a pending connection.  Raises ``OSError(EAGAIN)`` when
        none is queued."""
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
    # mbedTLS has parsed the cert + key into its internal structures;
    # drop the PEM buffers (~1–2 KB each) and reclaim before the
    # caller's next allocation lands.
    del cert_pem, key_pem
    gc.collect()
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
    """Wraps an MP listener so accept() yields TLS-wrapped sockets.

    Holds the inner :class:`_MpListeningSocketWrapper` on ``_sock``
    so :func:`chumicro_sockets.pollable_of` unwraps to a registrable
    listener for ``select.poll``.
    """

    def __init__(self, raw_listener, context):
        self._sock = raw_listener
        self._context = context

    def accept(self):
        new_wrapper, address = self._sock.accept()
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
        return _MpSocketWrapper(tls_sock), address

    def close(self):
        self._sock.close()

    def setblocking(self, flag):
        self._sock.setblocking(flag)


def ssl_context_with_ca(ca_pem):  # pragma: no cover - device only
    """Build an MP ``ssl.SSLContext`` that trusts only *ca_pem*.

    Accepts **PEM or DER**:

    * PEM (``-----BEGIN CERTIFICATE-----`` ... what ``openssl``
      produces by default) is converted to DER via
      :func:`_pem_to_der` and the DER is loaded.
    * DER (raw ASN.1, first byte ``0x30``) is loaded as-is.

    Conversion is **unconditional on MicroPython** — not gated on
    board type.  The expensive case (a large shipped trust bundle)
    is pre-converted to a DER data file and never reaches this path;
    a *user-supplied* CA is realistically one to a few certs, so the
    one-time `find`-scan + base64 decode at context-construction is
    sub-millisecond and not worth a fragile ``sys.platform`` branch.
    DER is the lowest-common-denominator that loads on every MP port
    (rp2's mbedTLS ships without ``MBEDTLS_PEM_PARSE_C``; esp builds
    have it — converting always sidesteps that split entirely).

    Multi-cert bundles (several ``-----BEGIN CERTIFICATE-----`` blocks
    back-to-back, or concatenated DER) are supported — mbedTLS's
    ``mbedtls_x509_crt_parse`` walks sequential DER certs natively.

    The returned context sets ``verify_mode = CERT_REQUIRED`` —
    loading a CA only makes sense when you intend to verify against
    it.

    Args:
        ca_pem: PEM or DER CA bundle as bytes / str / bytearray.
            Single cert or multi-cert bundle.

    Raises:
        ValueError: input is neither PEM nor DER-shaped.
    """
    import ssl  # noqa: PLC0415 — MP-only import

    if isinstance(ca_pem, str):
        ca_pem = ca_pem.encode("ascii")
    elif not isinstance(ca_pem, bytes):
        ca_pem = bytes(ca_pem)  # bytearray / memoryview

    if b"-----BEGIN CERTIFICATE-----" in ca_pem:
        cadata = _pem_to_der(ca_pem)
    elif ca_pem[:1] == b"\x30":  # ASN.1 SEQUENCE — already DER
        cadata = ca_pem
    else:
        raise ValueError(
            "ssl_context_with_ca expects PEM "
            "(-----BEGIN CERTIFICATE-----) or DER (ASN.1 SEQUENCE, "
            "first byte 0x30) — got neither",
        )

    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.load_verify_locations(cadata=cadata)
    context.verify_mode = ssl.CERT_REQUIRED
    # mbedTLS has copied the DER into its internal chain; the local
    # buffers (~16 KB for the shipped bundle) are dead weight from
    # here on.  Drop them and force a collection so the freed span
    # is available to the SSLContext / handshake working set instead
    # of fragmenting alongside it.  MP / CP GC is non-compacting.
    del cadata, ca_pem
    gc.collect()
    return context


def _pem_to_der(ca_pem):  # pragma: no cover - device only
    """Convert a PEM bundle (one or more certs) to concatenated DER bytes.

    Streaming: locates each ``-----BEGIN CERTIFICATE-----`` /
    ``-----END CERTIFICATE-----`` pair with C-level ``bytes.find``
    (no per-line Python loop), then base64-decodes the raw
    marker-to-marker slice directly.  ``binascii.a2b_base64`` skips
    every non-base64 byte — embedded ``\\n``, ``\\r``, spaces, blank
    lines — so no line splitting, whitespace stripping, or per-cert
    intermediate list is needed (verified: MP ``modbinascii.c`` does
    ``if (sextet == -1) continue``; CPython's default
    ``strict_mode=False`` behaves the same).

    *ca_pem* must be ``bytes`` (the caller normalizes).  Slices are
    taken through a ``memoryview`` so the per-cert base64 region is
    not copied before decoding; only the growing DER output and the
    final ``bytes()`` allocate.
    """
    import binascii  # noqa: PLC0415 — MP-only import

    begin_marker = b"-----BEGIN CERTIFICATE-----"
    end_marker = b"-----END CERTIFICATE-----"
    source = memoryview(ca_pem)
    der_out = bytearray()
    search_from = 0
    while True:
        begin_at = ca_pem.find(begin_marker, search_from)
        if begin_at < 0:
            break
        body_start = begin_at + len(begin_marker)
        end_at = ca_pem.find(end_marker, body_start)
        if end_at < 0:
            break
        der_out += binascii.a2b_base64(source[body_start:end_at])
        search_from = end_at + len(end_marker)
    return bytes(der_out)


#: PEM override installed via :func:`set_default_ca_bundle`.  ``None``
#: means "use the library-shipped bundle from
#: :mod:`chumicro_sockets._ca_bundle`."
_OVERRIDE_PEM = None

#: Module-level cache of the parsed default :class:`ssl.SSLContext`.
#: Invalidated when :func:`set_default_ca_bundle` changes the trust set.
_DEFAULT_CONTEXT_CACHE = None


def set_default_ca_bundle(pem_bytes):
    """Replace or revert the CA bundle used by ``connect_tls(context=None)``.

    Pass ``None`` to revert to the library-shipped bundle in
    :mod:`chumicro_sockets._ca_bundle`.  Pass PEM bytes (or str) to
    install a project-specific trust set — useful when the project
    talks to a server signed by a private internal CA, or when a public
    root we don't ship has rotated and the user needs to ship faster
    than our release cadence.

    The cached default context is invalidated; the next call to
    :func:`connect_tls` with ``context=None`` rebuilds it from the new
    bundle.
    """
    global _OVERRIDE_PEM, _DEFAULT_CONTEXT_CACHE
    _OVERRIDE_PEM = pem_bytes
    _DEFAULT_CONTEXT_CACHE = None


def _default_context():  # pragma: no cover - device only
    """Return the cached default :class:`ssl.SSLContext`, building on first use.

    When an override is set (:func:`set_default_ca_bundle`) the
    in-RAM override bytes are used.  Otherwise the shipped bundle is
    read from the sibling ``_ca_bundle.der`` data file via
    :func:`chumicro_sockets._ca_bundle.read_der`.

    The DER buffer is passed straight into ``ssl_context_with_ca`` as
    an unbound temporary and no reference is kept here, so it is
    collectable the moment ``load_verify_locations`` has copied it
    into mbedTLS — freed before the socket / handshake working set
    allocates (tight lifetime keeps fragmentation minimal; see
    ``_ca_bundle`` docstring).  Caching means plain-TCP-only callers
    never pay the read+parse, and TLS callers pay it exactly once.
    """
    global _DEFAULT_CONTEXT_CACHE
    if _DEFAULT_CONTEXT_CACHE is not None:
        return _DEFAULT_CONTEXT_CACHE
    if _OVERRIDE_PEM is not None:
        _DEFAULT_CONTEXT_CACHE = ssl_context_with_ca(_OVERRIDE_PEM)
        return _DEFAULT_CONTEXT_CACHE
    from chumicro_sockets import _ca_bundle  # noqa: PLC0415 — lazy

    _DEFAULT_CONTEXT_CACHE = ssl_context_with_ca(_ca_bundle.read_der())
    return _DEFAULT_CONTEXT_CACHE


def ssl_context_no_verify():  # pragma: no cover - device only
    """Return an MP ``ssl.SSLContext`` that **skips** certificate verification.

    Explicit opt-out for callers that intentionally don't want to
    validate the peer (dev against self-signed brokers, captive-portal
    probes, smoke tests against expired or untrusted hosts).  Named so
    code reviewers can grep for it — ``tls_client_socket(host, port,
    context=ssl_context_no_verify())`` shouts what it does.

    MP's :class:`ssl.SSLContext` constructed with
    ``PROTOCOL_TLS_CLIENT`` defaults to ``verify_mode =
    CERT_REQUIRED`` — this helper explicitly **downgrades** it to
    ``CERT_NONE`` so the opt-out is visible at the call site rather
    than silently in effect.
    """
    import ssl  # noqa: PLC0415 — runtime-gated

    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.verify_mode = ssl.CERT_NONE
    return context


def tcp_connector(host, port):  # pragma: no cover - device only
    """Return a tick-driven TCP :class:`SocketConnector` for MicroPython.

    Uses non-blocking ``socket.connect`` (raises ``OSError(EINPROGRESS)``
    on rp2 + esp32 ports) + ``select.poll(POLLOUT)`` for completion.
    DNS is synchronous (one phase tick); TCP is truly per-tick
    non-blocking — the connector yields between the dial and the
    POLLOUT-ready check, matching the CPython adapter's shape.
    """
    return _MpConnector(host, port, tls=False, context=None)


def tls_connector(host, port, *, context=None):  # pragma: no cover - device only
    """Return a tick-driven TLS :class:`SocketConnector` for MicroPython.

    Same per-tick shape as :func:`tcp_connector` for the DNS + TCP
    phases.  The TLS handshake itself happens **inside** MP's
    ``ssl.SSLContext.wrap_socket`` and BLOCKS for the round-trip:
    rp2 / esp32 mbedTLS builds do not expose a non-blocking handshake
    surface (no ``do_handshake_on_connect=False``).  Documented
    substrate limit; the ``awaiting_tls`` phase is a single blocking
    tick on this runtime.  Application traffic is non-blocking
    post-handshake.
    """
    return _MpConnector(host, port, tls=True, context=context)


class _MpConnector(SocketConnector):  # pragma: no cover - device only
    """MP non-blocking dialer — DNS + non-blocking TCP, blocking TLS.

    Three phases on the public surface (``awaiting_dns`` /
    ``awaiting_tcp`` / ``awaiting_tls``) match the runner-contract
    vocabulary, but the TLS phase is a single blocking tick: MP's
    mbedTLS ``ssl.SSLContext.wrap_socket`` performs the full handshake
    inline and does not expose ``do_handshake_on_connect=False``.

    A ``select.poll`` registration on the in-flight socket is
    constructed once at the first TCP-ready check and reused across
    ticks so the connector stays allocation-quiet on the runner-tick
    path.  Imports stay lazy at the method-body site to keep this file
    staged-but-quiet on CP (see module docstring).
    """

    def __init__(self, host, port, *, tls=False, context=None):
        super().__init__(host, port, tls=tls, context=context)
        self._addr_info = None
        # Pre-allocated when entering ``awaiting_tcp`` and reused
        # across subsequent ticks; cleared on transition out.
        self._tcp_poll = None

    def tick(self, now_ms):  # noqa: ARG002 (runner contract)
        if self.state in _TERMINAL:
            return
        try:
            if self.state == STATE_AWAITING_DNS:
                import socket  # noqa: PLC0415 — MP-only import

                self._addr_info = socket.getaddrinfo(self._host, self._port)[0]
                self.state = STATE_AWAITING_TCP
                return

            if self.state == STATE_AWAITING_TCP:
                if self._inflight_socket is None:
                    self._inflight_socket = self._issue_tcp_connect()
                    self._register_tcp_poll(self._inflight_socket)
                    return
                if not self._tcp_ready():
                    return
                self._tcp_poll = None
                if self._tls:
                    self._inflight_socket = self._wrap_tls(self._inflight_socket)
                    self.state = STATE_AWAITING_TLS
                else:
                    self.socket = _MpSocketWrapper(self._inflight_socket)
                    self._inflight_socket = None
                    self.state = STATE_READY
                return

            if self.state == STATE_AWAITING_TLS:
                # MP's ``wrap_socket`` already drove the handshake to
                # completion on entry; this tick just promotes.
                self.socket = _MpSocketWrapper(self._inflight_socket)
                self._inflight_socket = None
                self.state = STATE_READY
                return
        except Exception as error:  # noqa: BLE001 - any failure stops the machine
            self._fail(error)

    def _issue_tcp_connect(self):
        import errno  # noqa: PLC0415 — MP-only import
        import socket  # noqa: PLC0415 — MP-only import

        sock = socket.socket(self._addr_info[0], self._addr_info[1])
        sock.setblocking(False)
        try:
            sock.connect(self._addr_info[-1])
        except OSError as connect_exception:
            # Every MP port's non-blocking connect raises EINPROGRESS;
            # subsequent ticks drive the POLLOUT-ready check to
            # completion.  Comparison via ``errno.EINPROGRESS`` because
            # the integer value differs per lwIP port (115 on rp2, 119
            # on esp32-s2); any literal here would only work on the
            # port it was tested on.
            if connect_exception.errno != errno.EINPROGRESS:
                sock.close()
                raise
        return sock

    def _register_tcp_poll(self, sock):
        import select  # noqa: PLC0415 — MP-only import

        self._tcp_poll = select.poll()
        self._tcp_poll.register(sock, select.POLLOUT)

    def _tcp_ready(self):
        # POLLOUT firing means the kernel has resolved the connect
        # (success or failure).  POLLERR / POLLHUP would surface as
        # events too; the subsequent first ``send`` raises the actual
        # errno.  ``getsockopt(SO_ERROR)`` is not exposed reliably on
        # rp2 plain sockets, so we rely on POLLOUT + first-send-fails.
        events = self._tcp_poll.poll(0)  # 0 ms — non-blocking probe
        return bool(events)

    def _wrap_tls(self, sock):
        # ``ssl.SSLContext.wrap_socket`` blocks until the TLS handshake
        # completes — substrate limit documented on the public
        # ``tls_client_connector`` factory.  On the next tick the
        # ``awaiting_tls`` branch promotes to ``ready``.
        self._context = _resolve_default_context(self._context)
        return self._context.wrap_socket(sock, server_hostname=self._host)
