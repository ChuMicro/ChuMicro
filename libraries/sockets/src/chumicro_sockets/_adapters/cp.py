"""CircuitPython adapter — ``socketpool`` + native ``ssl``.

Every supported CP board ships the ``ssl`` module, so the TLS path
mirrors MP-mbedTLS and CPython: build (or accept) an
:class:`ssl.SSLContext`, call ``context.wrap_socket(socket,
server_hostname=host)``, then ``connect``.  Legacy radios without
on-board ``ssl`` (AirLift, pre-mbedTLS WIZNET5K, Fona) are out of
scope — those users stay on ``adafruit_connection_manager``.

Public surface (factory routes to these):

* ``connect_tcp(host, port, *, radio)`` — plain TCP.
* ``connect_tls(host, port, *, context, radio)`` — TLS, honoring the
  caller's context or building the default when ``context=None``.
* ``ssl_context_with_ca(ca_pem)`` — :class:`ssl.SSLContext` with custom CA.

``_pool_for(radio)`` memoizes the per-radio ``socketpool.SocketPool``
(steady-state cache size is one).
"""

__chumicro_runtimes__ = ("circuitpython",)

from chumicro_sockets.errors import UnsupportedSSLConfigError

#: Memoization cache: ``radio_id -> SocketPool``.  ``id(radio)`` keys
#: are stable for the lifetime of the radio object; CP boards have one
#: ``wifi.radio`` singleton per board, so the cache size is exactly
#: one in steady state.
_POOLS: dict = {}


def _pool_for(radio):
    """Return (or memoize) a ``socketpool.SocketPool`` for *radio*.

    *radio=None* auto-detects ``wifi.radio`` — the only radio on any
    production wifi-capable CP board.  Boards without a wifi module
    (SAMD M0 etc.) still get a ``TypeError`` directing them to pass
    ``radio=`` explicitly with whatever they're using.  Callers that
    want a non-default radio (multi-radio prototypes, AirLift, etc.)
    pass it explicitly and bypass the auto-detect.
    """
    if radio is None:
        try:
            import wifi  # noqa: PLC0415 — CP-only import
            radio = wifi.radio
        except (ImportError, AttributeError) as auto_detect_failure:
            raise TypeError(
                "CircuitPython adapter could not auto-detect a radio "
                "(`import wifi` failed). Pass radio= explicitly with "
                "whatever radio object your board exposes.",
            ) from auto_detect_failure
    cached = _POOLS.get(id(radio))
    if cached is not None:
        return cached
    import socketpool  # noqa: PLC0415 — CP-only import
    pool = socketpool.SocketPool(radio)
    _POOLS[id(radio)] = pool
    return pool


def connect_tcp(host, port, *, radio):
    """Open a plain TCP connection via the CP socketpool."""
    pool = _pool_for(radio)
    sock = pool.socket(pool.AF_INET, pool.SOCK_STREAM)
    sock.connect((host, port))
    return sock


def connect_tls(host, port, *, context=None, radio):
    """Open a TLS connection on a CP radio.

    *context=None* uses :func:`ssl.create_default_context` — picks up
    the system trust store, same code path as MP-mbedTLS and CPython.
    Any pre-built :class:`ssl.SSLContext` (e.g. from
    :func:`ssl_context_with_ca` for a custom CA) is accepted.
    """
    pool = _pool_for(radio)
    if context is None:
        # ``import ssl`` is gated on the *no caller-provided context*
        # branch so callers that hand us their own context don't pay
        # the import — relevant for unix-port testing where the CP
        # ``ssl.py`` shim still ImportErrors even after the
        # SSL+axtls build flag enable (axtls doesn't expose a
        # ``tls`` module the shim can find).
        import ssl  # noqa: PLC0415 — CP-only import

        context = ssl.create_default_context()
    raw = pool.socket(pool.AF_INET, pool.SOCK_STREAM)
    wrapped = context.wrap_socket(raw, server_hostname=host)
    wrapped.connect((host, port))
    return wrapped


def udp_socket(
    *,
    bind_host="0.0.0.0",
    bind_port=0,
    radio,
    broadcast=False,
):
    """Open a UDP socket on a CP radio, bound to (bind_host, bind_port).

    CP's ``socketpool`` supports ``AF_INET`` + ``SOCK_DGRAM`` (verified
    on CP 10.x for both ESP32-S2 and rp2).  Returns a wrapper that
    normalizes ``sendto`` to the separated ``(data, host, port)``
    signature and exposes ``recvfrom_into`` directly (CP's socketpool
    already exposes it natively as ``recvfrom_into(buffer)`` returning
    ``(nbytes, (host, port))``).

    ``SO_BROADCAST`` setup is best-effort: CP's socketpool does expose
    ``setsockopt`` on recent firmware, but older builds may not — we
    swallow ``OSError`` / ``AttributeError`` so the factory stays
    portable.
    """
    pool = _pool_for(radio)
    sock = pool.socket(pool.AF_INET, pool.SOCK_DGRAM)
    if broadcast:
        try:
            sock.setsockopt(pool.SOL_SOCKET, pool.SO_BROADCAST, 1)
        except (OSError, AttributeError):
            # Older CP firmware may lack SO_BROADCAST or setsockopt; non-fatal.
            pass
    sock.bind((bind_host, bind_port))
    return _CPUDPWrapper(sock)


class _CPUDPWrapper:
    """Adapts a CP socketpool UDP socket to the chumicro_sockets UDP protocol.

    Normalizes ``sendto`` to the separated ``(data, host, port)``
    signature.  CP's ``recvfrom_into(buffer)`` already returns the
    ``(nbytes, (host, port))`` tuple our protocol promises, so it's
    forwarded directly.
    """

    def __init__(self, sock):
        self._sock = sock
        self.close = sock.close
        self.setblocking = sock.setblocking
        # CP socketpool exposes settimeout on recent firmware; fall
        # back to a no-op so the protocol stays satisfied on older builds.
        self.settimeout = getattr(sock, "settimeout", lambda _seconds: None)
        forwarded_fileno = getattr(sock, "fileno", None)
        self.fileno = forwarded_fileno if forwarded_fileno is not None else (lambda: -1)
        forwarded_getsockname = getattr(sock, "getsockname", None)
        if forwarded_getsockname is not None:
            self.getsockname = forwarded_getsockname
        else:
            # CP socketpool may omit getsockname; report a placeholder.
            self.getsockname = lambda: ("0.0.0.0", 0)
        # CP's recvfrom_into returns (nbytes, address) — forward.
        self.recvfrom_into = sock.recvfrom_into

    def sendto(self, data, host, port):
        return self._sock.sendto(data, (host, port))


def listen_tcp(host, port, *, backlog=4, radio):
    """Open a non-blocking TCP listening socket via the CP socketpool.

    CP's ``socketpool.Socket`` exposes ``bind`` / ``listen`` / ``accept``
    (since CP 7.x).  ``accept()`` returns ``(new_socket, address)``.
    The new socket inherits the listener's blocking flag — we set the
    listener to non-blocking up front so accepts and per-connection
    recv/send don't stall the runner.
    """
    pool = _pool_for(radio)
    listener = pool.socket(pool.AF_INET, pool.SOCK_STREAM)
    # Best-effort SO_REUSEADDR so a back-to-back rebind on the same
    # port doesn't fail with OSError(EADDRINUSE) while a previous
    # socket is still in TIME_WAIT.  CP firmware exposure of
    # ``pool.SO_REUSEADDR`` and ``setsockopt`` is uneven (older CP /
    # rp2 ports may not have either); fall through silently when the
    # API is missing — back-to-back rebinds will fail then exactly as
    # they did before, but the common case (current CP on ESP32) gets
    # the same SO_REUSEADDR semantics as MP and CPython.
    try:
        listener.setsockopt(pool.SOL_SOCKET, pool.SO_REUSEADDR, 1)
    except (AttributeError, OSError):
        pass
    listener.bind((host, port))
    listener.listen(backlog)
    listener.setblocking(False)
    return listener


def ssl_context_with_cert_and_key(cert_pem, key_pem):
    """In-memory cert + key isn't supported on CP — paths are required.

    CircuitPython's ``ssl.SSLContext.load_cert_chain`` only accepts
    *filesystem paths*, not in-memory PEM bytes — passing bytes
    raises ``OSError(2, <pem-bytes>)`` because mbedTLS treats the
    bytes as a path it can't open.  Use
    :func:`ssl_context_with_cert_and_key_paths` instead.

    On MicroPython + CPython, the bytes-shaped helper works directly —
    only CP forces the path-based API.
    """
    raise UnsupportedSSLConfigError(
        "CircuitPython's ssl.SSLContext.load_cert_chain requires "
        "filesystem paths, not in-memory PEM bytes.  Call "
        "ssl_context_with_cert_and_key_paths(cert_path, key_path) "
        "instead — deploy the cert.pem + key.pem files to the device's "
        "/lib/ (or /) directory and pass their paths.",
    )


def ssl_context_with_cert_and_key_paths(cert_path, key_path):
    """Build a CP server-side SSLContext from cert + key file paths.

    Mirrors ``adafruit_httpserver``'s HTTPS path
    (verified live on Lolin S2 ESP32-S2 / CP 10.2.0-rc.0):

        ctx = ssl.create_default_context()
        ctx.load_verify_locations(cadata="")
        ctx.load_cert_chain(cert_path, key_path)

    CircuitPython's ``create_default_context()`` returns an
    ``SSLContext`` that's nominally client-side, but ``wrap_socket(sock,
    server_side=True)`` works on it as long as ``load_cert_chain`` has
    been called with valid cert + key paths.  The empty-cadata
    ``load_verify_locations`` call is required by CP's mbedTLS
    binding before ``load_cert_chain`` is accepted.

    Returns an ``ssl.SSLContext`` ready to pass to
    :func:`tls_listening_socket`.

    Args:
        cert_path: On-device filesystem path to the cert PEM file
            (e.g. ``"/lib/server_cert.pem"``).
        key_path: On-device filesystem path to the private-key PEM
            file (e.g. ``"/lib/server_key.pem"``).

    Live-verified on Lolin S2 ESP32-S2 with 6 KB context + 35 KB
    handshake heap cost, ~2 MB free heap remaining.  CP-rp2 boards
    (Pi Pico W / Pi Pico 2 W) are unsupported — :func:`listen_tls`
    refuses up-front via ``UnsupportedSSLConfigError``; this helper
    can still build the context but it'll have nowhere to go.
    """
    import ssl  # noqa: PLC0415 — CP-only import

    context = ssl.create_default_context()
    context.load_verify_locations(cadata="")
    context.load_cert_chain(cert_path, key_path)
    return context


def listen_tls(host, port, *, context, backlog=4, radio):
    """Open a non-blocking TLS listening socket via CP socketpool.

    Wraps the LISTENING socket with ``server_side=True`` before
    bind/listen — every accepted client inherits the TLS wrap.
    Mirrors adafruit_httpserver's `_create_server_socket`.  Verified
    on Lolin S2 ESP32-S2 / CP 10.2.0-rc.0.

    Refused on CP-rp2 (Pi Pico W / Pi Pico 2 W) — raises
    :class:`UnsupportedSSLConfigError`.  CP-rp2 lacks the
    ``server_side=True`` SSL wrap path; the adapter fails fast
    instead of letting the user discover that mid-handshake.
    """
    import sys  # noqa: PLC0415 - runtime detection only
    if sys.platform.upper().startswith("RP2"):
        from chumicro_sockets.errors import UnsupportedSSLConfigError  # noqa: PLC0415
        raise UnsupportedSSLConfigError(
            "TLS server not supported on CP-rp2 (Pi Pico W / Pi Pico 2 W). "
            "Use an ESP32-family board, or MicroPython on rp2."
        )
    pool = _pool_for(radio)
    raw = pool.socket(pool.AF_INET, pool.SOCK_STREAM)
    wrapped = context.wrap_socket(raw, server_side=True)
    wrapped.bind((host, port))
    wrapped.listen(backlog)
    wrapped.setblocking(False)
    return _CPTLSListenerWrapper(wrapped)


class _CPTLSListenerWrapper:
    """Wraps a CP TLS listener so accept() returns the standard
    ``(client_socket, address)`` tuple.

    The underlying CP wrapped-socket's ``accept()`` already returns
    a TLS-wrapped client socket (because the listener itself was
    wrapped) — we just normalize the return shape.
    """

    def __init__(self, wrapped_listener):
        self._sock = wrapped_listener

    def accept(self):
        return self._sock.accept()

    def close(self):
        self._sock.close()

    def setblocking(self, flag):
        self._sock.setblocking(flag)

    def fileno(self):
        return self._sock.fileno() if hasattr(self._sock, "fileno") else -1


def ssl_context_with_ca(ca_pem):
    """Build an SSL context that trusts *ca_pem* on a CP radio.

    **PEM only on CircuitPython.**  CP's ``load_verify_locations``
    binding takes an ASCII ``str``; DER (raw ASN.1 binary) is not
    ASCII-decodable, so it cannot be passed here.  We check for the
    ``-----BEGIN CERTIFICATE-----`` marker up front and raise a clear
    error if it is absent — otherwise a DER input would fail deep in
    ``.decode("ascii")`` with a cryptic ``UnicodeDecodeError``.  (MP
    accepts PEM *or* DER; CPython accepts either — this PEM-only
    constraint is specific to the CP binding.)

    The returned context inherits ``ssl.create_default_context``'s
    ``CERT_REQUIRED`` + ``check_hostname=True`` defaults — loading
    a custom CA only makes sense when you intend to verify against
    it.  Override on the returned context if a test or
    development scenario needs different behavior.

    Raises:
        ValueError: input is not PEM (no ``-----BEGIN CERTIFICATE-----``
            marker) — e.g. a DER blob, which CP cannot accept.
    """
    # Validate before importing ssl: the PEM check is pure string
    # inspection, and raising the clear error must not depend on the
    # ssl/tls binding being importable (it is absent on the CP
    # unix-port and on minimal builds).
    if isinstance(ca_pem, (bytes, bytearray)):
        if b"-----BEGIN CERTIFICATE-----" not in bytes(ca_pem):
            raise ValueError(
                "CircuitPython ssl_context_with_ca requires PEM input "
                "(-----BEGIN CERTIFICATE-----); CP's load_verify_locations "
                "binding cannot accept DER.  Convert to PEM, or pass DER "
                "only on MicroPython / CPython.",
            )
        ca_pem = bytes(ca_pem).decode("ascii")
    elif "-----BEGIN CERTIFICATE-----" not in ca_pem:
        raise ValueError(
            "CircuitPython ssl_context_with_ca requires PEM input "
            "(-----BEGIN CERTIFICATE-----); CP's load_verify_locations "
            "binding cannot accept DER.  Convert to PEM, or pass DER "
            "only on MicroPython / CPython.",
        )
    import ssl  # noqa: PLC0415 — CP-only import

    context = ssl.create_default_context()
    context.load_verify_locations(cadata=ca_pem)
    return context


def ssl_context_no_verify():
    """Return a CP ``ssl.SSLContext`` that **skips** certificate verification.

    Explicit opt-out for callers that intentionally don't want to
    validate the peer.  Named so code reviewers can grep for it —
    ``tls_client_socket(host, port, context=ssl_context_no_verify())``
    shouts what it does.

    Implementation: CircuitPython's :class:`ssl.SSLContext` exposes no
    settable ``verify_mode`` property — the authmode is decided at
    handshake time based on whether CAs were loaded.  Calling
    ``load_verify_locations("")`` with an empty string clears the
    firmware-attached CA bundle and sets ``cacert_bytes = 0``, which
    falls through to ``MBEDTLS_SSL_VERIFY_NONE`` at handshake (see
    CP's ``shared-module/ssl/SSLSocket.c``).  ``check_hostname = False``
    matches the other runtimes' opt-out shape.
    """
    import ssl  # noqa: PLC0415 — CP-only import

    context = ssl.create_default_context()
    context.load_verify_locations(cadata="")
    context.check_hostname = False
    return context
