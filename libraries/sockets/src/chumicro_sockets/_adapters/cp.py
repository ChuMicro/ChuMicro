"""CircuitPython adapter — ``socketpool`` + native ``ssl``.

Decision 0015 caps the supported board class at 256 KB MCU RAM /
4 MB flash and current-LTS firmware.  Every CP board in that class
with native wifi (Pi Pico W, ESP32-S2, ESP32-S3, ESP32-S3 Feather,
etc.) ships the ``ssl`` module — so the TLS path is the same shape
as MP-mbedTLS and CPython: build (or accept) an
:class:`ssl.SSLContext`, call ``context.wrap_socket(socket,
server_hostname=host)``, then ``connect``.

Legacy radios that lack the on-board ``ssl`` module (AirLift,
WIZNET5K-pre-mbedTLS, Fona) used a ``TLS_MODE``-flag fake-context
shim — out of scope here.  Users on those boards should pin to the
existing ``adafruit_connection_manager`` ecosystem rather than
chumicro-sockets.

Public surface from this module (everything the package's factories
route to):

* ``connect_tcp(host, port, *, radio)`` — plain TCP.
* ``connect_tls(host, port, *, context, radio)`` — TLS, honoring the
  caller's context or building the default when ``context=None``.
* ``ssl_context_with_ca(ca_pem)`` — real :class:`ssl.SSLContext`
  with custom CA.

``_pool_for(radio)`` memoizes the per-radio ``socketpool.SocketPool``
so a fresh pool isn't built on every connect (CP creates one pool
per radio; the cache size is exactly one in steady state).
"""


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


def ssl_context_with_ca(ca_pem):  # pragma: no cover - device only
    """Build an SSL context that trusts *ca_pem* on a CP radio.

    Identical shape to the CPython and MP helpers — supported CP
    boards ship the on-board ``ssl`` module so the call site is
    uniform across runtimes.
    """
    import ssl  # noqa: PLC0415 — CP-only import

    context = ssl.create_default_context()
    context.load_verify_locations(cadata=ca_pem.decode("ascii"))
    return context
