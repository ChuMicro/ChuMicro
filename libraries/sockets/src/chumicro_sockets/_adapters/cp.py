"""CircuitPython adapter: ``socketpool`` plus native ``ssl``.

Every supported CP board ships the ``ssl`` module, so the TLS path mirrors the
MicroPython and CPython adapters. Legacy radios without on-board ``ssl``
(AirLift, pre-mbedTLS WIZNET5K, Fona) are out of scope. ``ssl`` is a lazy
in-function import in every TLS-using helper so plain-TCP consumers do not pay
its heap cost; ``socketpool`` is eager because every path here uses it.
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

# Single-pool module cache: every wifi-capable CP board exposes one
# ``wifi.radio``, so a one-slot cache is enough (no per-radio dict needed).
_POOL = None


def _pool_for(radio):
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


def _resolve_default_context(context):
    if context is not None:
        return context
    import ssl  # noqa: PLC0415
    return ssl.create_default_context()


def udp_socket(
    *,
    bind_host="0.0.0.0",
    bind_port=0,
    radio,
    broadcast=False,
):
    """Open a UDP socket on a CP radio, bound to (bind_host, bind_port).

    Wraps the socketpool socket so ``sendto`` takes separated ``(data, host,
    port)`` args. ``SO_BROADCAST`` setup is best-effort on older firmware.
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
    def __init__(self, sock):
        self.sock = sock
        self.close = sock.close
        self.setblocking = sock.setblocking
        # settimeout exists only on recent firmware; fall back to a no-op.
        self.settimeout = getattr(sock, "settimeout", lambda _seconds: None)
        # Bare-metal socketpool has no getsockname (the unix build does);
        # forward it only when the port provides it.
        if hasattr(sock, "getsockname"):
            self.getsockname = sock.getsockname
        # CP's recvfrom_into already returns (nbytes, address); forward it.
        self.recvfrom_into = sock.recvfrom_into

    def sendto(self, data, host, port):
        return self.sock.sendto(data, (host, port))


def listener(host, port, *, tls=False, context=None, backlog=4, radio=None):
    """Open a non-blocking TCP or TLS listening socket via the CP socketpool.

    The listener is set non-blocking up front so accepts and per-connection I/O
    do not stall the runner. With ``tls=True`` the listening socket is wrapped
    ``server_side=True`` before bind/listen, so accepted clients inherit the TLS
    wrap. Refused on CP-rp2 (Pi Pico W / Pi Pico 2 W), where that path raises
    ``OSError(32)`` mid-handshake and wedges the CYW43 chip until a USB
    power-cycle.
    """
    if tls and sys.platform.upper().startswith("RP2"):
        raise UnsupportedSSLConfigError(
            "TLS server not supported on CP-rp2 (Pi Pico W / Pi Pico 2 W). "
            "Use an ESP32-family board, or MicroPython on rp2."
        )
    pool = _pool_for(radio)
    sock = pool.socket(pool.AF_INET, pool.SOCK_STREAM)
    if tls:
        sock = context.wrap_socket(sock, server_side=True)
    # Best-effort SO_REUSEADDR so a quick rebind does not hit EADDRINUSE while
    # the old socket is in TIME_WAIT. CP firmware exposure is uneven, so ignore
    # a missing option or setsockopt.
    try:
        sock.setsockopt(pool.SOL_SOCKET, pool.SO_REUSEADDR, 1)
    except (AttributeError, OSError):
        pass
    sock.bind((host, port))
    sock.listen(backlog)
    sock.setblocking(False)
    return sock


def ssl_context_with_cert_and_key(cert_pem, key_pem):
    """Not supported on CircuitPython: raises ``UnsupportedSSLConfigError``.

    CP's ``ssl.SSLContext.load_cert_chain`` accepts only filesystem paths, so
    passing in-memory PEM bytes fails. Use
    :func:`ssl_context_with_cert_and_key_paths` instead.
    """
    raise UnsupportedSSLConfigError(
        "CircuitPython's ssl.SSLContext.load_cert_chain requires "
        "filesystem paths, not in-memory PEM bytes.  Call "
        "ssl_context_with_cert_and_key_paths(cert_path, key_path) "
        "instead; deploy the cert.pem + key.pem files to the device's "
        "/lib/ (or /) directory and pass their paths.",
    )


def ssl_context_with_cert_and_key_paths(cert_path, key_path):
    """Build a CP server-side SSLContext from cert and key file paths.

    CP-rp2 boards are unsupported: ``listener(tls=True)`` refuses up front there,
    so the context this builds would have nowhere to go.
    """
    import ssl  # noqa: PLC0415

    context = ssl.create_default_context()
    # CP's mbedTLS binding requires this empty-cadata call before load_cert_chain.
    context.load_verify_locations(cadata="")
    context.load_cert_chain(cert_path, key_path)
    return context


def ssl_context_with_ca(ca_pem):
    """Build a CP SSLContext that trusts *ca_pem*. PEM only.

    CP's ``load_verify_locations`` binding takes an ASCII ``str``, so a DER blob
    is rejected up front with a clear ``ValueError`` rather than failing deep in
    ``.decode("ascii")``. The context keeps ``create_default_context``'s
    ``CERT_REQUIRED`` + ``check_hostname=True`` defaults.

    Raises:
        ValueError: The input is not PEM (DER is not accepted on CircuitPython).
    """
    # Validate before importing ssl: the PEM check is pure string inspection and
    # must not depend on the ssl binding, which is absent on the CP unix-port.
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
    import ssl  # noqa: PLC0415

    context = ssl.create_default_context()
    context.load_verify_locations(cadata=ca_pem)
    # mbedTLS has copied the PEM into its chain; drop the buffer and collect so
    # the freed span is reused rather than fragmenting (CP GC is non-compacting).
    del ca_pem
    gc.collect()
    return context


def ssl_context_no_verify():
    """Return a CP ``ssl.SSLContext`` that skips certificate verification.

    An explicit opt-out for callers that intentionally do not validate the peer;
    named so reviewers can grep for it. CP has no settable ``verify_mode``, so
    this clears the CA bundle via ``load_verify_locations("")`` (which falls
    through to no verification at handshake) and sets ``check_hostname = False``.
    """
    import ssl  # noqa: PLC0415

    context = ssl.create_default_context()
    context.load_verify_locations(cadata="")
    context.check_hostname = False
    return context


def connector(host, port, *, tls=False, context=None, radio=None):
    """Return a tick-driven connector for CircuitPython.

    CP's ``socketpool`` connect is synchronous, so the dial splits into DNS and
    TCP ticks but each blocks for its substrate call. With ``tls=True`` the
    handshake runs inside the same blocking ``connect()``, so there is no
    separate ``awaiting_tls`` phase on CP.
    """
    return _CPConnector(host, port, tls=tls, context=context, radio=radio)


class _CPConnector(SocketConnector):
    """CP dialer: DNS, then one blocking connect that runs TCP and any TLS."""

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
                # Assign the raw socket immediately so ``_fail()`` can close it
                # even if wrap_socket below raises, avoiding a leaked pool socket.
                self.socket = sock
                if self._tls:
                    self._context = _resolve_default_context(self._context)
                    sock = self._context.wrap_socket(
                        sock, server_hostname=self._host,
                    )
                    self.socket = sock  # rebind so _fail closes the wrapper
                # Blocking connect: completes TCP and, if wrapped, the TLS
                # handshake before returning.
                sock.connect(self.sockaddr)
                self.state = STATE_READY
                return
        except Exception as error:  # noqa: BLE001 - any failure stops the machine
            self._fail(error)


# Defragment compile-time scratch at module bottom so the lazy load
# from chumicro_sockets's factories lands in a cleaner heap.
gc.collect()
