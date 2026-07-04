"""Cross-runtime TCP + TLS + UDP sockets for CircuitPython, MicroPython, and CPython.

Public API::

    from chumicro_sockets import (
        UnsupportedSSLConfigError, # raised when the requested TLS shape isn't supported
        connector,                 # non-blocking tick-driven TCP/TLS connect
        listener,                  # TCP/TLS listening socket
        udp_socket,                # UDP datagram factory (unicast + broadcast)
        ssl_context_with_ca,       # custom-CA helper
    )

    from chumicro_sockets.testing import FakeSocket, FakeUDPSocket

Per-runtime adapters live under ``_adapters/``; the public entries
(``connector`` / ``listener`` / ``udp_socket``) pick the right adapter
via ``sys.implementation.name`` so user code never sees a runtime
check.  TLS is a ``tls=`` flag plus an optionally injected
``ssl.SSLContext`` — ``context=None`` verifies against the runtime's
default trust store; the path is identical across runtimes (every
supported board ships on-board ``ssl``).

There is one connect implementation per runtime: the tick-driven
``SocketConnector`` state machine that ``connector()`` returns.
Code that wants a connected socket right now (a one-shot script, REPL
exploration, ``main`` before the runner loop starts) drives the same
machine to terminal inline::

    conn = connector("example.com", 80, radio=radio)
    while conn.state not in ("ready", "failed"):
        conn.tick(0)
    if conn.state == "failed":
        raise conn.last_error
    sock = conn.socket

Substrate for ``chumicro-mqtt``, ``chumicro-requests``,
``chumicro-websockets``, ``chumicro-http-server`` (TCP/TLS), and
``chumicro-ntp`` (UDP).  Returned sockets are duck-typed: TCP exposes
``send`` / ``recv_into`` / ``close`` / ``setblocking`` / ``settimeout``;
UDP exposes ``sendto`` / ``recvfrom_into`` / ``close`` /
``setblocking`` / ``settimeout`` / ``getsockname``.  Downstream libs
hold the returned socket and call those methods directly.
"""

import gc
import sys


class UnsupportedSSLConfigError(RuntimeError):
    """Raised when the requested TLS configuration isn't supported on this runtime.

    Two firing sites today: ``listener(tls=True)`` on CP-rp2
    (Pi Pico W / Pi Pico 2 W), where ``wrap_socket(server_side=True) +
    accept()`` raises ``OSError(32)`` mid-handshake and wedges the CYW43
    station-mode state until USB power-cycle; and
    ``ssl_context_with_cert_and_key`` on CircuitPython, whose
    ``load_cert_chain`` needs filesystem paths rather than in-memory PEM
    bytes (use ``ssl_context_with_cert_and_key_paths`` there).  Downstream
    libs ``except`` it so an unsupported TLS shape surfaces as a
    structured failure instead of an ``AttributeError``.
    """


__all__ = [
    "UnsupportedSSLConfigError",
    "connector",
    "listener",
    "set_default_ca_bundle",
    "ssl_context_no_verify",
    "ssl_context_with_ca",
    "ssl_context_with_cert_and_key",
    "ssl_context_with_cert_and_key_paths",
    "udp_socket",
]


#: Per-package adapter cache — populated on first factory call.
#: Lazy first-use rather than eager so ``import chumicro_sockets``
#: succeeds on unix-port runtimes that don't ship the substrate
#: (CP unix-port has no ``socketpool``, MP unix-port build varies).
#: Tests that never touch a factory don't pay for the substrate import.
#: Tests that drive a specific runtime swap this binding directly.
_adapter = None


def _get_adapter():
    """Return the resolved per-runtime adapter, importing on first call.

    First-call resolution amortizes runtime dispatch across the
    public factories — they each call ``_get_adapter().method(...)``
    instead of carrying their own runtime branch.  The cache is a
    module-level binding tests can swap directly via ``_adapter``.
    """
    global _adapter
    if _adapter is not None:
        return _adapter
    runtime = sys.implementation.name
    if runtime == "circuitpython":  # pragma: no cover - runtime-gated; never hits on host pytest
        from chumicro_sockets._adapters import cp as resolved  # noqa: PLC0415
    elif runtime == "micropython":  # pragma: no cover - runtime-gated; never hits on host pytest
        from chumicro_sockets._adapters import mp as resolved  # noqa: PLC0415
    else:
        from chumicro_sockets._adapters import cpython as resolved  # noqa: PLC0415
    _adapter = resolved
    return _adapter


def connector(
    host: str,
    port: int,
    *,
    tls: bool = False,
    context: object | None = None,
    radio: object | None = None,
) -> object:
    """Return a non-blocking tick-driven TCP/TLS connector.

    The one connect entry point.  The returned ``SocketConnector``
    advances DNS → TCP → (optional TLS) across multiple
    ``tick(now_ms)`` calls; once ``state == "ready"``, the connected
    socket is available on ``connector.socket``.  See
    :mod:`chumicro_sockets._connector` for the state diagram.  The
    connector exposes the runner-contract surface (``check`` /
    ``handle`` / ``io_socket`` / ``io_interest`` / ``next_deadline`` /
    ``cancel``), so ``Runner.add(connector(...))`` registers it raw and
    ``chumicro_sockets.generators.connect`` drives it from a generator.

    Per-runtime substrate honesty:

    * **CPython** — truly non-blocking TCP (``BlockingIOError`` /
      EINPROGRESS + ``select`` + ``SO_ERROR``) and TLS
      (``do_handshake_on_connect=False`` + ``do_handshake()`` looped
      across ticks).
    * **MicroPython rp2 / esp32** — truly non-blocking TCP via
      ``OSError(EINPROGRESS)`` + ``select.poll(POLLOUT)``; the TLS
      handshake blocks inline in ``ssl.wrap_socket`` (mbedTLS exposes
      no non-blocking handshake surface) — a single substrate-blocking
      phase tick.
    * **CircuitPython** — per-phase blocking: ``socketpool`` exposes no
      non-blocking connect, and TCP + TLS collapse into one blocking
      ``wrapped_socket.connect()`` call.  Honest documented compromise.

    The ``awaiting_dns`` phase resolves *host* with a synchronous
    ``getaddrinfo`` on every runtime, so a cache miss against a slow
    resolver blocks the runner for the lookup.  Pass an IP literal to
    skip it when the address is already known.

    ``tls=True, context=None`` verifies on every runtime:

    * **CircuitPython** — the firmware-bundled mbedTLS CA store.
    * **CPython** — ``ssl.create_default_context()``; the host OS
      trust store.
    * **MicroPython** — the library-shipped CA bundle (17 roots; see
      :func:`set_default_ca_bundle` to override).

    For explicit no-verification (dev against self-signed brokers,
    captive-portal probes), pass ``context=ssl_context_no_verify()``
    — named so the opt-out is greppable in code review.

    Args:
        host: DNS name or IP literal.  With ``tls=True`` it is also the
            ``server_hostname`` for the handshake (SNI + cert
            verification).
        port: Remote port.
        tls: ``True`` wraps the connection in TLS.
        context: SSLContext for the ``tls=True`` path.  ``None`` =
            runtime default trust.  Pre-build via
            :func:`ssl_context_with_ca` for custom CAs.  Ignored when
            ``tls=False``.
        radio: CP-only radio object — pass ``wifi.radio`` on CP boards;
            ignored on MP and CPython.

    Returns:
        ``SocketConnector`` in ``"awaiting_dns"`` — call ``tick``
        until terminal.
    """
    return _get_adapter().connector(host, port, tls=tls, context=context, radio=radio)


def listener(
    host: str,
    port: int,
    *,
    tls: bool = False,
    context: object | None = None,
    backlog: int = 4,
    radio: object | None = None,
) -> object:
    """Open a non-blocking TCP or TLS listening socket.

    Routes to the runtime-appropriate adapter:

    * **CircuitPython** — ``socketpool.SocketPool(radio).socket().bind().listen()``
      (since CP 7.x).  ``setsockopt(SO_REUSEADDR, 1)`` is best-effort
      (older CP firmware / rp2 ports may not expose the option).
      *radio* is required (typically ``wifi.radio``).
    * **MicroPython** — ``socket.socket().bind().listen()``;
      ``SO_REUSEADDR`` best-effort.  *radio* is ignored.
    * **CPython** — stdlib ``socket.socket().bind().listen()`` with
      ``SO_REUSEADDR`` set.  *radio* is ignored.

    The returned listener is in non-blocking mode — ``accept()``
    returns ``(client_socket, address)`` when a connection is ready
    or raises ``OSError(EAGAIN)`` when the queue is empty.  Substrate
    for ``chumicro-http-server`` and the websockets server.

    With ``tls=True`` a server-side ``ssl.SSLContext`` (built via
    :func:`ssl_context_with_cert_and_key` /
    :func:`ssl_context_with_cert_and_key_paths`) is required, and each
    accepted client is TLS-wrapped before ``accept()`` returns it.
    The TLS handshake happens **synchronously** inside ``accept()`` —
    on Pi Pico W class boards this can take 100-500 ms per connection
    and visibly stall the runner during that window.  Acceptable when
    ``max_connections=1`` and the handshake budget is bounded; if the
    LED-blink invariant matters more than TLS, terminate TLS in front
    of the board with a proxy (Caddy / nginx / Cloudflare Tunnel) and
    let the board speak plain HTTP on the LAN behind it.

    Args:
        host: Address to bind to.  ``"0.0.0.0"`` accepts on every
            interface (typical for boards on a single LAN).
        port: TCP port to bind.
        tls: ``True`` TLS-wraps every accepted client.
        context: Server-side ``ssl.SSLContext``.  Required when
            ``tls=True``; ignored otherwise.
        backlog: SYN-queue depth for incoming connections.  4 is a
            reasonable default for a small-IoT server; raise for
            higher-volume listeners.
        radio: CP-only radio object — pass ``wifi.radio`` on CP boards;
            ignored on MP and CPython.

    Returns:
        A listening socket object exposing ``accept()`` / ``close()``
        / ``setblocking()``.

    Raises:
        ValueError: ``tls=True`` without a *context*.
        OSError: Bind / listen failed (port in use, permission denied,
            etc.).
        UnsupportedSSLConfigError: ``tls=True`` on CP-rp2 boards.
        TypeError: CP runtime invoked with ``radio=None``.
    """
    if tls and context is None:
        raise ValueError(
            "listener(tls=True) requires a server-side context= — build "
            "one via ssl_context_with_cert_and_key(_paths)",
        )
    return _get_adapter().listener(
        host, port, tls=tls, context=context, backlog=backlog, radio=radio,
    )


def ssl_context_with_cert_and_key(
    cert_pem: str | bytes,
    key_pem: str | bytes,
) -> object:
    """Build a server-side SSLContext from in-memory cert + key bytes.

    Counterpart to :func:`ssl_context_with_ca` — the client side
    trusts a CA to verify someone *else's* cert, while the server
    side presents its own cert + private key to clients.

    **Runtime support:**

    * **MicroPython** — works directly with PEM (or DER on rp2)
      bytes via MP's ``ssl.SSLContext.load_cert_chain``.
    * **CPython** — works (writes to a temp file).
    * **CircuitPython** — *not supported* (CP's
      ``load_cert_chain`` requires filesystem paths, not bytes).
      Use :func:`ssl_context_with_cert_and_key_paths` instead.

    Args:
        cert_pem: PEM-encoded server certificate (or chain).
        key_pem: PEM-encoded private key matching the cert.

    Returns:
        Configured :class:`ssl.SSLContext`.
    """
    return _get_adapter().ssl_context_with_cert_and_key(cert_pem, key_pem)


def ssl_context_with_cert_and_key_paths(
    cert_path: str,
    key_path: str,
) -> object:
    """Build a server-side SSLContext from cert + key files on flash.

    Cross-runtime alternative to :func:`ssl_context_with_cert_and_key`
    that works on every supported runtime — CircuitPython's
    ``ssl.SSLContext.load_cert_chain`` only accepts filesystem paths,
    so this is the recommended API for CP-targeted code.

    On MicroPython + CPython this reads the bytes from the paths
    and routes through :func:`ssl_context_with_cert_and_key`.  On
    CircuitPython it loads via the path directly.

    Unsupported on CP-rp2 (Pi Pico W / Pi Pico 2 W) —
    ``listener(tls=True)`` refuses up-front there.

    Args:
        cert_path: On-device filesystem path to the cert PEM file.
        key_path: On-device filesystem path to the private-key PEM
            file.

    Returns:
        Configured :class:`ssl.SSLContext`.
    """
    adapter = _get_adapter()
    if hasattr(adapter, "ssl_context_with_cert_and_key_paths"):
        return adapter.ssl_context_with_cert_and_key_paths(cert_path, key_path)
    # MP + CPython: load the bytes and use the in-memory helper.
    with open(cert_path, "rb") as cert_handle:
        cert_bytes = cert_handle.read()
    with open(key_path, "rb") as key_handle:
        key_bytes = key_handle.read()
    context = adapter.ssl_context_with_cert_and_key(cert_bytes, key_bytes)
    # mbedTLS / stdlib ssl has parsed the PEM into the context; drop
    # the file buffers (~1–2 KB each) and force a collection before
    # the caller's next allocation lands.
    del cert_bytes, key_bytes
    gc.collect()
    return context


def udp_socket(
    bind_host: str = "0.0.0.0",
    bind_port: int = 0,
    *,
    radio: object | None = None,
    broadcast: bool = False,
):
    """Open a UDP datagram socket.

    Routes to the runtime-appropriate adapter:

    * **CircuitPython** —
      ``socketpool.SocketPool(radio).socket(AF_INET, SOCK_DGRAM)``,
      ``bind((bind_host, bind_port))``, optional ``setsockopt(SOL_SOCKET,
      SO_BROADCAST, 1)``.  *radio* is required (typically ``wifi.radio``).
    * **MicroPython** — stdlib ``socket.socket(AF_INET, SOCK_DGRAM)``
      + ``bind`` + optional ``SO_BROADCAST``.  *radio* is ignored.
    * **CPython** — stdlib ``socket.socket(AF_INET, SOCK_DGRAM)`` +
      ``bind`` + optional ``SO_BROADCAST``.  *radio* is ignored.

    The default ``bind_host="0.0.0.0"``, ``bind_port=0`` requests an
    ephemeral port on every interface — the OS picks a free port and
    binds it.  Pass ``bind_port=N`` for a server / receiver that
    listens on a known port (NTP responses, mDNS replies, etc.).

    Call ``getsockname()`` on the returned socket to learn the bound
    address — useful when ``bind_port=0`` and the caller needs to
    know which port the OS assigned.

    Args:
        bind_host: Local address to bind.  ``"0.0.0.0"`` accepts on
            every interface (the typical case for boards on a single
            LAN).
        bind_port: Local port.  ``0`` = ephemeral.
        radio: CP-only radio object — pass ``wifi.radio`` on CP boards;
            ignored on MP and CPython.
        broadcast: Set ``SO_BROADCAST`` so ``sendto`` to a broadcast
            address (typically ``"255.255.255.255"`` or the LAN
            broadcast address) succeeds.  Off by default — kernels
            reject broadcast sends without it.

    Returns: Bound UDP socket.

    Raises:
        OSError: Bind failed (port in use, permission denied, etc.).
        TypeError: CP runtime invoked with ``radio=None``.
    """
    return _get_adapter().udp_socket(
        bind_host=bind_host,
        bind_port=bind_port,
        radio=radio,
        broadcast=broadcast,
    )


def ssl_context_with_ca(ca_pem: str | bytes) -> object:
    """Build an SSLContext that trusts the CA(s) in *ca_pem*.

    The common "default everything except the trust anchor" recipe.
    Returned as ``object`` rather than ``ssl.SSLContext`` so we don't
    force ``import ssl`` at module-load time on plain-TCP-only
    consumers.

    Input format acceptance is **not uniform** — it follows what each
    runtime's ``ssl`` binding can take:

    * **MicroPython** — PEM *or* DER.  PEM is converted to DER
      internally (unconditionally — see the MP adapter); DER is loaded
      as-is.  DER is preferred for user-supplied CAs on MP-targeted
      code: it skips the conversion and is the only format the rp2
      mbedTLS build accepts.
    * **CPython** — PEM *or* DER (stdlib accepts both).
    * **CircuitPython** — **PEM only**.  CP's ``load_verify_locations``
      binding takes an ASCII ``str``; a DER blob raises ``ValueError``
      up front rather than failing cryptically.

    Multi-cert bundles (concatenated PEM blocks or concatenated DER)
    are supported on every runtime.

    "PEM" here means the RFC 7468 certificate encoding — the exact
    ``-----BEGIN CERTIFICATE-----`` / ``-----END CERTIFICATE-----``
    boundary that ``openssl``, the Mozilla/curl bundle, and Let's
    Encrypt all emit.  Alternate armors are **not** auto-handled and
    raise ``ValueError`` (never silent mistrust): a legacy
    ``X509 CERTIFICATE`` label, ``TRUSTED CERTIFICATE`` (carries extra
    trust data), ``PKCS7`` containers, or bare unarmored base64.
    Re-export those as a standard ``CERTIFICATE`` PEM, or pass DER.

    Args:
        ca_pem: CA bundle.  PEM (``str``/``bytes``) on every runtime;
            DER (``bytes``) on MicroPython + CPython only.

    Returns:
        Configured :class:`ssl.SSLContext`.

    Raises:
        ValueError: input is not an accepted format for the runtime
            (e.g. DER on CircuitPython, or neither PEM nor DER).
    """
    return _get_adapter().ssl_context_with_ca(ca_pem)


def ssl_context_no_verify() -> object:
    """Return an SSLContext that **skips** certificate verification.

    Explicit opt-out for callers that intentionally don't want to
    validate the peer — dev against self-signed brokers, captive-portal
    probes, smoke tests against expired or untrusted hosts.  Named so
    code reviewers can grep for it; using this where
    ``ssl_context_with_ca`` would do is a security defect.

    Returns:
        Configured :class:`ssl.SSLContext` with verification disabled.
        Shape varies per runtime — CP relies on the empty-string
        ``load_verify_locations`` idiom; MP + CPython set
        ``verify_mode = CERT_NONE`` directly.
    """
    return _get_adapter().ssl_context_no_verify()


def set_default_ca_bundle(pem_bytes: bytes | str | None) -> None:
    """Replace or revert the CA bundle used by ``connector(tls=True, context=None)``.

    On **MicroPython** the library ships a curated 17-root CA bundle
    (Let's Encrypt, DigiCert, Amazon, Google, GlobalSign, Sectigo,
    GoDaddy/Starfield, Entrust, Microsoft) consumed by the
    default-secure ``tls=True, context=None`` path.  Call this to
    swap in a project-specific bundle — useful when the
    deployment talks to a server signed by a private internal CA, or
    when a public root not in our shipped set has rotated and the
    project needs to ship faster than our release cadence.

    Pass ``None`` to revert to the library-shipped bundle.

    **No-op on CircuitPython and CPython** — those runtimes get their
    trust roots from the firmware bundle (CP) or the host OS trust
    store (CPython); changing this library's bundle has no effect on
    either path.

    Args:
        pem_bytes: PEM-encoded CA bundle (single or multi-cert) as
            bytes or str, or ``None`` to revert.
    """
    adapter = _get_adapter()
    if hasattr(adapter, "set_default_ca_bundle"):
        adapter.set_default_ca_bundle(pem_bytes)
    # CP + CPython: trust comes from elsewhere — silently ignore.


# Defragment compile-time scratch at the end of the package import so
# the consumer's first allocation lands in a cleaner heap.
gc.collect()
