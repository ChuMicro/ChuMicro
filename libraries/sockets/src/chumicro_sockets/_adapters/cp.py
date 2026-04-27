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


def _pool_for(radio):  # pragma: no cover - device only
    """Return (or memoize) a ``socketpool.SocketPool`` for *radio*."""
    if radio is None:
        raise TypeError(
            "CircuitPython adapter requires a radio= argument "
            "(typically wifi.radio)",
        )
    cached = _POOLS.get(id(radio))
    if cached is not None:
        return cached
    import socketpool  # noqa: PLC0415 — CP-only import
    pool = socketpool.SocketPool(radio)
    _POOLS[id(radio)] = pool
    return pool


def connect_tcp(host, port, *, radio):  # pragma: no cover - device only
    """Open a plain TCP connection via the CP socketpool."""
    pool = _pool_for(radio)
    sock = pool.socket(pool.AF_INET, pool.SOCK_STREAM)
    sock.connect((host, port))
    return sock


def connect_tls(host, port, *, context=None, radio):  # pragma: no cover - device only
    """Open a TLS connection on a CP radio.

    *context=None* uses :func:`ssl.create_default_context` — picks up
    the system trust store, same code path as MP-mbedTLS and CPython.
    Any pre-built :class:`ssl.SSLContext` (e.g. from
    :func:`ssl_context_with_ca` for a custom CA) is accepted.
    """
    import ssl  # noqa: PLC0415 — CP-only import

    pool = _pool_for(radio)
    resolved_context = context if context is not None else ssl.create_default_context()
    raw = pool.socket(pool.AF_INET, pool.SOCK_STREAM)
    wrapped = resolved_context.wrap_socket(raw, server_hostname=host)
    wrapped.connect((host, port))
    return wrapped


def listen_tcp(host, port, *, backlog=4, radio):  # pragma: no cover - device only
    """Open a non-blocking TCP listening socket via the CP socketpool.

    CP's ``socketpool.Socket`` exposes ``bind`` / ``listen`` / ``accept``
    (since CP 7.x).  ``accept()`` returns ``(new_socket, address)``.
    The new socket inherits the listener's blocking flag — we set the
    listener to non-blocking up front so accepts and per-connection
    recv/send don't stall the runner.
    """
    pool = _pool_for(radio)
    listener = pool.socket(pool.AF_INET, pool.SOCK_STREAM)
    # CP's socketpool doesn't expose SO_REUSEADDR directly; rebind on a
    # quick restart can fail with OSError(EADDRINUSE).  We accept that
    # — Pi Pico W users will rarely restart so fast it matters, and
    # exposing the option requires runtime-private socket constants.
    listener.bind((host, port))
    listener.listen(backlog)
    listener.setblocking(False)
    return listener


def ssl_context_with_cert_and_key(cert_pem, key_pem):  # pragma: no cover - device only
    """Server-side TLS on CircuitPython is not supported.

    CircuitPython's `ssl` module deliberately omits
    `PROTOCOL_TLS_SERVER` (verified live on CP 10.2.0-rc.0 against
    Pi Pico W: ``dir(ssl)`` exposes no ``PROTOCOL_*`` constants).
    The `ssl.SSLContext()` exposed by CP is hard-wired to the
    client side.  This is a CP-platform limitation, not a heap
    constraint — adafruit_httpserver's ``https=True`` flag is
    similarly inert on CP for the same reason.

    Slice 7t verified TLS server **does** fit on Pi Pico W
    MicroPython (8 KB context + 25 KB handshake, 130 KB free
    heap remaining).  CP users who want HTTPS on a Pi Pico W
    must terminate TLS in front of the board (Caddy / nginx /
    Cloudflare Tunnel) and let the board speak plain HTTP on
    the LAN behind it.
    """
    raise UnsupportedSSLConfigError(
        "CircuitPython's ssl module does not expose PROTOCOL_TLS_SERVER; "
        "server-side TLS is not supported on CP.  Use chumicro-http-server "
        "behind a TLS-terminating proxy instead, or run on MicroPython "
        "(slice 7t verified TLS server on Pi Pico W MP).",
    )


def listen_tls(host, port, *, context, backlog=4, radio):  # pragma: no cover - device only
    """Server-side TLS on CircuitPython is not supported.

    See :func:`ssl_context_with_cert_and_key` for the platform-
    limitation explanation.  This stub raises immediately so callers
    get a clear error rather than silently constructing a half-built
    listener.
    """
    raise UnsupportedSSLConfigError(
        "CircuitPython does not support server-side TLS — "
        "tls_listening_socket is not available on CP.  See "
        "chumicro_sockets._adapters.cp.ssl_context_with_cert_and_key "
        "for the recommended workaround (TLS-terminating proxy in "
        "front of the board).",
    )


class _CPTLSListenerWrapper:  # pragma: no cover - device only
    """Wraps a CP listening socket so accept() yields TLS-wrapped sockets."""

    def __init__(self, raw_listener, context):
        self._raw = raw_listener
        self._context = context

    def accept(self):
        client_raw, address = self._raw.accept()
        # CP's `wrap_socket(server_side=True)` performs the TLS
        # handshake synchronously.  Make the raw socket blocking
        # for the handshake (CP's mbedTLS doesn't support
        # async server handshake), then back to non-blocking.
        client_raw.setblocking(True)
        try:
            wrapped = self._context.wrap_socket(
                client_raw, server_side=True,
            )
        except Exception:
            client_raw.close()
            raise
        # Some CP builds reject `setblocking(False)` on SSLSocket;
        # try and swallow.
        try:
            wrapped.setblocking(False)
        except (AttributeError, OSError):
            pass
        return wrapped, address

    def close(self):
        self._raw.close()

    def setblocking(self, flag):
        self._raw.setblocking(flag)

    def fileno(self):
        return self._raw.fileno() if hasattr(self._raw, "fileno") else -1


def ssl_context_with_ca(ca_pem):  # pragma: no cover - device only
    """Build an SSL context that trusts *ca_pem* on a CP radio.

    Identical shape to the CPython and MP helpers — supported CP
    boards ship the on-board ``ssl`` module so the call site is
    uniform across runtimes.  Accepts PEM as ``str`` or ``bytes``;
    CP's ``load_verify_locations`` expects a ``str`` so we coerce.

    The returned context inherits ``ssl.create_default_context``'s
    ``CERT_REQUIRED`` + ``check_hostname=True`` defaults — loading
    a custom CA only makes sense when you intend to verify against
    it.  Override on the returned context if a test or
    development scenario needs different behavior.
    """
    import ssl  # noqa: PLC0415 — CP-only import

    if isinstance(ca_pem, (bytes, bytearray)):
        ca_pem = bytes(ca_pem).decode("ascii")
    context = ssl.create_default_context()
    context.load_verify_locations(cadata=ca_pem)
    return context
