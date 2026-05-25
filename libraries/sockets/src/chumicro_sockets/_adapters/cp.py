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

import gc
import sys

import socketpool

from chumicro_sockets import UnsupportedSSLConfigError
from chumicro_sockets._connector import (
    _TERMINAL,
    STATE_AWAITING_DNS,
    STATE_AWAITING_TCP,
    STATE_READY,
    SocketConnector,
)

#: Single-pool module cache.  Every production wifi-capable CP board
#: exposes one ``wifi.radio`` singleton, and ``socketpool.SocketPool``
#: only ever wraps that one radio in this codebase — so a one-slot
#: cache is enough and the dict-keyed-by-id pattern from
#: ``adafruit_connection_manager`` (which dispatches across radio
#: classes) is not.
_POOL = None


def _pool_for(radio):
    """Return the module-cached ``socketpool.SocketPool``, building on first use.

    *radio* must be a concrete CP radio object — typically ``wifi.radio``.
    The adapter does not auto-import ``wifi`` to backfill ``None``;
    callers pass the radio they already have so there is no implicit
    network-stack import the user did not ask for.
    """
    global _POOL
    if _POOL is not None:
        return _POOL
    if radio is None:
        raise TypeError(
            "chumicro_sockets requires a CircuitPython radio object on CP. "
            "Pass radio=wifi.radio (or the radio your board exposes).",
        )
    _POOL = socketpool.SocketPool(radio)
    return _POOL


def connect_tcp(host, port, *, radio):
    """Open a plain TCP connection via the CP socketpool."""
    pool = _pool_for(radio)
    sock = pool.socket(pool.AF_INET, pool.SOCK_STREAM)
    sock.connect((host, port))
    return sock


def _resolve_default_context(context):
    """Return *context* unchanged, or build CP's default context if ``None``.

    ``ssl.create_default_context()`` picks up the firmware-bundled
    mbedTLS CA store — the standard verify path on every CP board.
    Import is lazy: callers that hand us their own context skip the
    ssl module load entirely, and host-side tests against the CP
    unix-port (which lacks the ``tls`` C module the ssl shim looks
    for) only fail when they reach a non-context-providing call site.
    """
    if context is not None:
        return context
    import ssl  # noqa: PLC0415 — CP-only import; lazy per docstring
    return ssl.create_default_context()


def connect_tls(host, port, *, context=None, radio):
    """Open a TLS connection on a CP radio.

    *context=None* uses :func:`ssl.create_default_context` — picks up
    the system trust store, same code path as MP-mbedTLS and CPython.
    Any pre-built :class:`ssl.SSLContext` (e.g. from
    :func:`ssl_context_with_ca` for a custom CA) is accepted.
    """
    pool = _pool_for(radio)
    context = _resolve_default_context(context)
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
        self.sock = sock
        self.close = sock.close
        self.setblocking = sock.setblocking
        # CP socketpool exposes settimeout on recent firmware; fall
        # back to a no-op so the protocol stays satisfied on older builds.
        self.settimeout = getattr(sock, "settimeout", lambda _seconds: None)
        self.getsockname = sock.getsockname
        # CP's recvfrom_into returns (nbytes, address) — forward.
        self.recvfrom_into = sock.recvfrom_into

    def sendto(self, data, host, port):
        return self.sock.sendto(data, (host, port))


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

    CircuitPython's ``create_default_context()`` returns a context
    that's nominally client-side, but ``wrap_socket(sock,
    server_side=True)`` works on it once ``load_cert_chain`` has
    loaded valid cert + key paths.  The empty-cadata
    ``load_verify_locations(cadata="")`` call before
    ``load_cert_chain`` is required by CP's mbedTLS binding —
    without it ``load_cert_chain`` is refused.

    Args:
        cert_path: On-device filesystem path to the cert PEM file
            (e.g. ``"/lib/server_cert.pem"``).
        key_path: On-device filesystem path to the private-key PEM
            file (e.g. ``"/lib/server_key.pem"``).

    Returns:
        An ``ssl.SSLContext`` ready to pass to
        :func:`tls_listening_socket`.

    CP-rp2 boards (Pi Pico W / Pi Pico 2 W) are unsupported —
    :func:`listen_tls` refuses up-front via
    ``UnsupportedSSLConfigError``; this helper can still build the
    context but it'll have nowhere to go.
    """
    import ssl  # noqa: PLC0415 — CP-only import

    context = ssl.create_default_context()
    context.load_verify_locations(cadata="")
    context.load_cert_chain(cert_path, key_path)
    return context


def listen_tls(host, port, *, context, backlog=4, radio):
    """Open a non-blocking TLS listening socket via CP socketpool.

    Wraps the LISTENING socket with ``server_side=True`` before
    bind/listen — every accepted client inherits the TLS wrap, so
    ``accept()`` returns ``(tls_client_socket, address)`` directly.

    Refused on CP-rp2 (Pi Pico W / Pi Pico 2 W) — raises
    :class:`UnsupportedSSLConfigError`.  ``wrap_socket(server_side=True)
    + accept()`` raises ``OSError(32)`` mid-handshake on the CP-rp2
    port AND wedges the CYW43 chip's station-mode state until USB
    power-cycle; the adapter fails fast instead of letting the user
    discover that mid-handshake.
    """
    if sys.platform.upper().startswith("RP2"):
        raise UnsupportedSSLConfigError(
            "TLS server not supported on CP-rp2 (Pi Pico W / Pi Pico 2 W). "
            "Use an ESP32-family board, or MicroPython on rp2."
        )
    pool = _pool_for(radio)
    raw = pool.socket(pool.AF_INET, pool.SOCK_STREAM)
    tls_listener = context.wrap_socket(raw, server_side=True)
    tls_listener.bind((host, port))
    tls_listener.listen(backlog)
    tls_listener.setblocking(False)
    return tls_listener


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
    # mbedTLS has copied the PEM into its chain; drop the local
    # buffer + force a collection so the freed span is available to
    # the next allocation instead of fragmenting alongside the
    # SSLContext.  CP GC is non-compacting.
    del ca_pem
    gc.collect()
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


def tcp_connector(host, port, *, radio=None):
    """Return a tick-driven TCP connector for CircuitPython.

    CP's ``socketpool.SocketPool.socket().connect()`` is synchronous;
    the connector splits the dial into per-phase ticks (DNS, then TCP)
    but each phase blocks for its substrate-level call.  Honest
    documented compromise: better than the all-blocking-in-one-call
    synchronous factory, not yet truly non-blocking the way the
    CPython adapter is.
    """
    return _CPConnector(host, port, tls=False, context=None, radio=radio)


def tls_connector(host, port, *, context=None, radio=None):
    """Return a tick-driven TLS connector for CircuitPython.

    CP's TLS handshake happens inside ``wrapped_socket.connect()`` —
    the substrate does not separate TCP and TLS.  The connector wraps
    the socket before the TCP-connect phase and goes straight to
    ``ready`` after that single blocking call; there is no separate
    ``awaiting_tls`` phase on CP.
    """
    return _CPConnector(host, port, tls=True, context=context, radio=radio)


class _CPConnector(SocketConnector):
    """CP dialer — DNS, then a single blocking connect that runs both
    TCP and (optionally) TLS.

    Two phases on the public surface (``awaiting_dns`` /
    ``awaiting_tcp``) — CP's ``socketpool`` does not expose a
    non-blocking connect, so the TCP step blocks for the kernel
    handshake duration.  When TLS is requested the socket is wrapped
    with ``server_hostname`` *before* ``connect()`` so the substrate
    runs the TLS handshake in the same blocking call; the connector
    never enters ``awaiting_tls`` on CP.

    Honest documented compromise — better than the all-blocking-in-one
    synchronous factory because DNS and connect get their own ticks,
    but not truly non-blocking the way the CPython adapter is.
    """

    def __init__(self, host, port, *, tls=False, context=None, radio=None):
        super().__init__(host, port, tls=tls, context=context)
        self._radio = radio
        self.sockaddr = None

    def tick(self, now_ms):  # noqa: ARG002 (runner contract)
        if self.state in _TERMINAL:
            return
        try:
            if self.state == STATE_AWAITING_DNS:
                pool = _pool_for(self._radio)
                addr_info = pool.getaddrinfo(
                    self._host, self._port, pool.AF_INET, pool.SOCK_STREAM,
                )[0]
                self.sockaddr = addr_info[4]
                self.state = STATE_AWAITING_TCP
                return

            if self.state == STATE_AWAITING_TCP:
                pool = _pool_for(self._radio)
                sock = pool.socket(pool.AF_INET, pool.SOCK_STREAM)
                if self._tls:
                    self._context = _resolve_default_context(self._context)
                    sock = self._context.wrap_socket(
                        sock, server_hostname=self._host,
                    )
                # Blocking connect — completes TCP and (if wrapped)
                # the TLS handshake before returning.
                sock.connect(self.sockaddr)
                self.socket = sock
                self.state = STATE_READY
                return
        except Exception as error:  # noqa: BLE001 - any failure stops the machine
            self._fail(error)


# Defragment compile-time scratch at module bottom so the lazy load
# from chumicro_sockets's factories lands in a cleaner heap.
gc.collect()
