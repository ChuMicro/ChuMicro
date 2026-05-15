"""Cross-runtime TCP + TLS + UDP sockets for CircuitPython, MicroPython, and CPython.

Public API::

    from chumicro_sockets import (
        TCPClientSocket,           # TCP protocol every adapter implements
        UDPSocket,                 # UDP protocol every adapter implements
        UnsupportedSSLConfigError, # raised when the requested TLS shape isn't supported
        tcp_client_socket,         # plain-TCP factory
        tls_client_socket,         # TLS factory
        udp_socket,                # UDP datagram factory (unicast + broadcast)
        ssl_context_with_ca,       # custom-CA helper
        is_eagain,                 # would-block detector for non-blocking recv/send loops
    )

    from chumicro_sockets.testing import FakeSocket, FakeUDPSocket

Per-runtime adapters live under ``_adapters/``; sibling factories
(``tcp_client_socket`` / ``tls_client_socket`` / ``udp_socket``)
pick the right adapter via ``sys.implementation.name`` so user code
never sees a runtime check.  TLS is an injected ``ssl.SSLContext``
(not a flag); the path is identical across runtimes — every supported
board ships on-board ``ssl``.

Substrate for ``chumicro-mqtt``, ``chumicro-requests``,
``chumicro-http-server`` (TCP/TLS), and ``chumicro-ntp`` (UDP).
Downstream libs annotate against ``TCPClientSocket`` / ``UDPSocket``
instead of importing ``socketpool`` / ``socket`` / ``ssl`` directly.
"""

import sys

from chumicro_sockets.errors import UnsupportedSSLConfigError
from chumicro_sockets.protocol import TCPClientSocket, UDPSocket

__all__ = [
    "TCPClientSocket",
    "UDPSocket",
    "UnsupportedSSLConfigError",
    "is_eagain",
    "set_default_ca_bundle",
    "ssl_context_no_verify",
    "ssl_context_with_ca",
    "ssl_context_with_cert_and_key",
    "ssl_context_with_cert_and_key_paths",
    "tcp_client_socket",
    "tcp_listening_socket",
    "tls_client_socket",
    "tls_listening_socket",
    "udp_socket",
]


def is_eagain(exception: BaseException) -> bool:
    """``True`` if *exception* signals "would block, retry next tick".

    Matches ``OSError(errno=11)`` (Linux / MP / CP) and ``35`` (macOS
    CPython).  Custom-factory sockets must raise one of these on
    non-blocking would-block — consumers' recv loops use this to
    distinguish retry from a real socket error.
    """
    errno = getattr(exception, "errno", None)
    return errno == 11 or errno == 35


def _runtime_name() -> str:
    """Return ``sys.implementation.name`` (``"cpython"`` / ``"micropython"`` /
    ``"circuitpython"``).  Wrapped so tests can patch it cleanly."""
    return sys.implementation.name


def tcp_client_socket(host: str, port: int, *, radio: object | None = None) -> TCPClientSocket:
    """Open a plain TCP client connection.

    Routes to the runtime-appropriate adapter:

    * **CircuitPython** — ``socketpool.SocketPool(radio).socket(...).connect``.
      *radio* defaults to ``wifi.radio``; pass explicitly for multi-radio
      prototypes or boards without a ``wifi`` module.
    * **MicroPython** — stdlib ``socket.socket`` + ``connect``.
      *radio* is ignored.
    * **CPython** — stdlib ``socket.create_connection``.  *radio* is ignored.

    Args:
        host: DNS name or IP literal.
        port: Remote port.
        radio: CP-only radio object.  Defaults to ``wifi.radio`` on CP;
            ignored on MP and CPython.  Pass explicitly for multi-radio
            prototypes or CP boards without a ``wifi`` module.

    Returns:
        Connected :class:`TCPClientSocket`.  Already connected — callers
        do not see a separate ``connect`` step.

    Raises:
        OSError: Connection refused, DNS failure, etc.  Adapters
            normalize runtime-specific socket errors into ``OSError``.
        TypeError: CP runtime invoked on a board where ``import wifi``
            fails and no explicit ``radio=`` was passed.
    """
    runtime = _runtime_name()
    if runtime == "circuitpython":
        from chumicro_sockets._adapters import cp  # noqa: PLC0415 — runtime-gated import

        return cp.connect_tcp(host, port, radio=radio)
    if runtime == "micropython":
        from chumicro_sockets._adapters import mp  # noqa: PLC0415 — runtime-gated import

        return mp.connect_tcp(host, port)
    # CPython + anything else stdlib-shaped (e.g. PyPy).
    from chumicro_sockets._adapters import cpython  # noqa: PLC0415 — runtime-gated import

    return cpython.connect_tcp(host, port)


def tls_client_socket(
    host: str,
    port: int,
    *,
    context: object | None = None,
    radio: object | None = None,
) -> TCPClientSocket:
    """Open a TLS client connection.

    Routes to the runtime-appropriate adapter; *context* is honored
    on every runtime (every supported board ships on-board ``ssl``):

    * **CircuitPython** — ``context.wrap_socket(socketpool_sock,
      server_hostname=host)`` then ``connect``.  *radio* defaults to
      ``wifi.radio``.
    * **MicroPython** — same shape via MP's ``ssl.SSLContext``
      (mbedTLS-backed on RP2 + ESP32 from MP 1.24+).
    * **CPython** — stdlib ``ssl.SSLContext.wrap_socket``.

    *context=None* verifies on every runtime:

    * **CircuitPython** — verifies against the firmware-bundled
      mbedTLS CA store (``x509-crt-bundle``).
    * **CPython** — ``ssl.create_default_context()``; verifies against
      the host OS trust store.
    * **MicroPython** — verifies against the library-shipped CA
      bundle (17 roots: Let's Encrypt, DigiCert, Amazon, Google,
      GlobalSign, Sectigo, GoDaddy/Starfield, Entrust, Microsoft —
      a strict subset of CP's firmware bundle; see
      :func:`set_default_ca_bundle` to override).

    For explicit no-verification (dev against self-signed brokers,
    captive-portal probes), pass ``context=ssl_context_no_verify()``
    — named so the opt-out is greppable in code review.

    Args:
        host: DNS name or IP literal.  Used as ``server_hostname``
            for the TLS handshake (SNI + cert verification).
        port: Remote port.
        context: SSLContext to use.  ``None`` = runtime default.
            Pre-build via :func:`ssl_context_with_ca` for custom CAs.
        radio: CP-only radio object.  Defaults to ``wifi.radio`` on CP;
            ignored on MP and CPython.  Pass explicitly for multi-radio
            prototypes or CP boards without a ``wifi`` module.

    Returns:
        Connected, TLS-wrapped :class:`TCPClientSocket`.

    Raises:
        OSError: Connection or handshake failure.
        TypeError: CP runtime invoked on a board where ``import wifi``
            fails and no explicit ``radio=`` was passed.
    """
    runtime = _runtime_name()
    if runtime == "circuitpython":
        from chumicro_sockets._adapters import cp  # noqa: PLC0415 — runtime-gated import

        return cp.connect_tls(host, port, context=context, radio=radio)
    if runtime == "micropython":
        from chumicro_sockets._adapters import mp  # noqa: PLC0415 — runtime-gated import

        return mp.connect_tls(host, port, context=context)
    from chumicro_sockets._adapters import cpython  # noqa: PLC0415 — runtime-gated import

    return cpython.connect_tls(host, port, context=context)


def tcp_listening_socket(
    host: str,
    port: int,
    *,
    backlog: int = 4,
    radio: object | None = None,
) -> object:
    """Open a non-blocking TCP listening socket.

    Routes to the runtime-appropriate adapter:

    * **CircuitPython** — ``socketpool.SocketPool(radio).socket().bind().listen()``
      (since CP 7.x).  ``setsockopt(SO_REUSEADDR, 1)`` is best-effort
      (older CP firmware / rp2 ports may not expose the option).
      *radio* defaults to ``wifi.radio``; pass explicitly for multi-radio
      prototypes or boards without a ``wifi`` module.
    * **MicroPython** — ``socket.socket().bind().listen()``;
      ``setsockopt(SO_REUSEADDR, 1)`` is best-effort (some ports don't
      expose the option).  *radio* is ignored.
    * **CPython** — stdlib ``socket.socket().bind().listen()`` with
      ``SO_REUSEADDR`` set.  *radio* is ignored.

    The returned listener is in non-blocking mode — ``accept()``
    returns ``(client_socket, address)`` when a connection is ready
    or raises ``OSError(EAGAIN)`` when the queue is empty.  Substrate
    for ``chumicro-http-server``.

    Args:
        host: Address to bind to.  ``"0.0.0.0"`` accepts on every
            interface (typical for boards on a single LAN).
        port: TCP port to bind.
        backlog: SYN-queue depth for incoming connections.  4 is a
            reasonable default for a small-IoT server; raise for
            higher-volume listeners.
        radio: CP-only radio object.  Required on CP, ignored
            elsewhere.

    Returns:
        A listening socket object exposing ``accept()`` / ``close()``
        / ``setblocking()`` / ``fileno()``.

    Raises:
        OSError: Bind / listen failed (port in use, permission denied,
            etc.).
        TypeError: CP runtime invoked on a board where ``import wifi``
            fails and no explicit ``radio=`` was passed.
    """
    runtime = _runtime_name()
    if runtime == "circuitpython":
        from chumicro_sockets._adapters import cp  # noqa: PLC0415 — runtime-gated

        return cp.listen_tcp(host, port, backlog=backlog, radio=radio)
    if runtime == "micropython":
        from chumicro_sockets._adapters import mp  # noqa: PLC0415 — runtime-gated

        return mp.listen_tcp(host, port, backlog=backlog)
    from chumicro_sockets._adapters import cpython  # noqa: PLC0415 — runtime-gated

    return cpython.listen_tcp(host, port, backlog=backlog)


def tls_listening_socket(
    host: str,
    port: int,
    *,
    context: object,
    backlog: int = 4,
    radio: object | None = None,
) -> object:
    """Open a non-blocking TLS listening socket.

    Same shape as :func:`tcp_listening_socket` but accepts a server-
    side ``ssl.SSLContext`` and wraps each accepted client in TLS
    before returning it from ``accept()``.  Build the context via
    :func:`ssl_context_with_cert_and_key`.

    The TLS handshake happens **synchronously** inside ``accept()`` —
    on Pi Pico W class boards this can take 100-500 ms per
    connection and visibly stall the runner during that window.
    Acceptable when ``max_connections=1`` and the handshake budget
    is bounded; if the LED-blink invariant matters for your use
    case more than TLS, terminate TLS in front of the board with a
    proxy (Caddy / nginx / Cloudflare Tunnel) and let the board
    speak plain HTTP on the LAN behind it.

    Args:
        host: Address to bind to.
        port: TCP port to bind.
        context: Server-side ``ssl.SSLContext`` from
            :func:`ssl_context_with_cert_and_key`.
        backlog: SYN-queue depth.
        radio: CP-only radio object.  Defaults to ``wifi.radio`` on CP;
            ignored on MP and CPython.

    Returns:
        A listening socket wrapper whose ``accept()`` returns
        ``(tls_wrapped_socket, address)``.
    """
    runtime = _runtime_name()
    if runtime == "circuitpython":
        from chumicro_sockets._adapters import cp  # noqa: PLC0415 — runtime-gated

        return cp.listen_tls(host, port, context=context, backlog=backlog, radio=radio)
    if runtime == "micropython":
        from chumicro_sockets._adapters import mp  # noqa: PLC0415 — runtime-gated

        return mp.listen_tls(host, port, context=context, backlog=backlog)
    from chumicro_sockets._adapters import cpython  # noqa: PLC0415 — runtime-gated

    return cpython.listen_tls(host, port, context=context, backlog=backlog)


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
    * **CPython** — works (writes to a temp file under the hood).
    * **CircuitPython** — *not supported* (CP's
      ``load_cert_chain`` requires filesystem paths, not bytes).
      Use :func:`ssl_context_with_cert_and_key_paths` instead.

    Args:
        cert_pem: PEM-encoded server certificate (or chain).
        key_pem: PEM-encoded private key matching the cert.

    Returns:
        Configured :class:`ssl.SSLContext`.
    """
    runtime = _runtime_name()
    if runtime == "circuitpython":
        from chumicro_sockets._adapters import cp  # noqa: PLC0415 — runtime-gated

        return cp.ssl_context_with_cert_and_key(cert_pem, key_pem)
    if runtime == "micropython":
        from chumicro_sockets._adapters import mp  # noqa: PLC0415 — runtime-gated

        return mp.ssl_context_with_cert_and_key(cert_pem, key_pem)
    from chumicro_sockets._adapters import cpython  # noqa: PLC0415 — runtime-gated

    return cpython.ssl_context_with_cert_and_key(cert_pem, key_pem)


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

    Live-verified on Lolin S2 ESP32-S2 (CP 10.2.0-rc.0): 6 KB
    context + 35 KB handshake heap cost, ~2 MB free heap
    remaining; HTTPS GET round-trip from a host CPython client
    succeeded.  CP-rp2 (Pi Pico W / Pi Pico 2 W) is unsupported —
    :func:`tls_listening_socket` refuses up-front there.

    Args:
        cert_path: On-device filesystem path to the cert PEM file.
        key_path: On-device filesystem path to the private-key PEM
            file.

    Returns:
        Configured :class:`ssl.SSLContext`.
    """
    runtime = _runtime_name()
    if runtime == "circuitpython":
        from chumicro_sockets._adapters import cp  # noqa: PLC0415 — runtime-gated

        return cp.ssl_context_with_cert_and_key_paths(cert_path, key_path)
    # MP + CPython: load the bytes and use the in-memory helper.
    with open(cert_path, "rb") as cert_handle:
        cert_bytes = cert_handle.read()
    with open(key_path, "rb") as key_handle:
        key_bytes = key_handle.read()
    if runtime == "micropython":
        from chumicro_sockets._adapters import mp  # noqa: PLC0415 — runtime-gated

        return mp.ssl_context_with_cert_and_key(cert_bytes, key_bytes)
    from chumicro_sockets._adapters import cpython  # noqa: PLC0415 — runtime-gated

    return cpython.ssl_context_with_cert_and_key(cert_bytes, key_bytes)


def udp_socket(
    bind_host: str = "0.0.0.0",
    bind_port: int = 0,
    *,
    radio: object | None = None,
    broadcast: bool = False,
) -> UDPSocket:
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

    Use :meth:`UDPSocket.getsockname` after construction to learn
    the bound address — useful when ``bind_port=0`` and the caller
    needs to know which port the OS assigned.

    Args:
        bind_host: Local address to bind.  ``"0.0.0.0"`` accepts on
            every interface (the typical case for boards on a single
            LAN).
        bind_port: Local port.  ``0`` = ephemeral.
        radio: CP-only radio object.  Defaults to ``wifi.radio`` on CP;
            ignored on MP and CPython.  Pass explicitly for multi-radio
            prototypes or CP boards without a ``wifi`` module.
        broadcast: Set ``SO_BROADCAST`` so ``sendto`` to a broadcast
            address (typically ``"255.255.255.255"`` or the LAN
            broadcast address) succeeds.  Off by default — kernels
            reject broadcast sends without it.

    Returns:
        Bound :class:`UDPSocket`.

    Raises:
        OSError: Bind failed (port in use, permission denied, etc.).
        TypeError: CP runtime invoked on a board where ``import wifi``
            fails and no explicit ``radio=`` was passed.
    """
    runtime = _runtime_name()
    if runtime == "circuitpython":
        from chumicro_sockets._adapters import cp  # noqa: PLC0415 — runtime-gated

        return cp.udp_socket(
            bind_host=bind_host,
            bind_port=bind_port,
            radio=radio,
            broadcast=broadcast,
        )
    if runtime == "micropython":
        from chumicro_sockets._adapters import mp  # noqa: PLC0415 — runtime-gated

        return mp.udp_socket(
            bind_host=bind_host,
            bind_port=bind_port,
            broadcast=broadcast,
        )
    from chumicro_sockets._adapters import cpython  # noqa: PLC0415 — runtime-gated

    return cpython.udp_socket(
        bind_host=bind_host,
        bind_port=bind_port,
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
    runtime = _runtime_name()
    if runtime == "circuitpython":
        from chumicro_sockets._adapters import cp  # noqa: PLC0415 — runtime-gated import

        return cp.ssl_context_with_ca(ca_pem)
    if runtime == "micropython":
        from chumicro_sockets._adapters import mp  # noqa: PLC0415 — runtime-gated import

        return mp.ssl_context_with_ca(ca_pem)
    from chumicro_sockets._adapters import cpython  # noqa: PLC0415 — runtime-gated import

    return cpython.ssl_context_with_ca(ca_pem)


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
    runtime = _runtime_name()
    if runtime == "circuitpython":
        from chumicro_sockets._adapters import cp  # noqa: PLC0415 — runtime-gated

        return cp.ssl_context_no_verify()
    if runtime == "micropython":
        from chumicro_sockets._adapters import mp  # noqa: PLC0415 — runtime-gated

        return mp.ssl_context_no_verify()
    from chumicro_sockets._adapters import cpython  # noqa: PLC0415 — runtime-gated

    return cpython.ssl_context_no_verify()


def set_default_ca_bundle(pem_bytes: bytes | str | None) -> None:
    """Replace or revert the CA bundle used by ``tls_client_socket(context=None)``.

    On **MicroPython** the library ships a curated 17-root CA bundle
    (Let's Encrypt, DigiCert, Amazon, Google, GlobalSign, Sectigo,
    GoDaddy/Starfield, Entrust, Microsoft) consumed by the
    default-secure ``connect_tls(context=None)`` path.  Call this to
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
    if _runtime_name() == "micropython":
        from chumicro_sockets._adapters import mp  # noqa: PLC0415 — runtime-gated

        mp.set_default_ca_bundle(pem_bytes)
    # CP + CPython: trust comes from elsewhere — silently ignore.
