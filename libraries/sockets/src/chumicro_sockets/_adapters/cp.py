"""CircuitPython adapter: ``socketpool`` plus native ``ssl``."""

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

# One wifi.radio per CP board, so a single-slot cache is enough.
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
    """Open a UDP socket on a CP radio, bound to (bind_host, bind_port)."""
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
        # Bare-metal socketpool lacks getsockname (the unix build has it); forward only when present.
        if hasattr(sock, "getsockname"):
            self.getsockname = sock.getsockname
        self.recvfrom_into = sock.recvfrom_into

    def sendto(self, data, host, port):
        return self.sock.sendto(data, (host, port))


def listener(host, port, *, tls=False, context=None, backlog=4, radio=None):
    """Open a non-blocking TCP or TLS listening socket via the CP socketpool."""
    if tls and sys.platform.upper().startswith("RP2"):
        raise UnsupportedSSLConfigError(
            "TLS server not supported on CP-rp2 (Pi Pico W / Pi Pico 2 W). "
            "Use an ESP32-family board, or MicroPython on rp2."
        )
    pool = _pool_for(radio)
    sock = pool.socket(pool.AF_INET, pool.SOCK_STREAM)
    if tls:
        sock = context.wrap_socket(sock, server_side=True)
    # Best-effort SO_REUSEADDR; CP firmware exposure is uneven, so ignore if missing.
    try:
        sock.setsockopt(pool.SOL_SOCKET, pool.SO_REUSEADDR, 1)
    except (AttributeError, OSError):
        pass
    sock.bind((host, port))
    sock.listen(backlog)
    sock.setblocking(False)
    return sock


def ssl_context_with_cert_and_key(cert_pem, key_pem):
    """Not supported on CircuitPython: raises ``UnsupportedSSLConfigError``."""
    raise UnsupportedSSLConfigError(
        "CircuitPython's ssl.SSLContext.load_cert_chain requires "
        "filesystem paths, not in-memory PEM bytes.  Call "
        "ssl_context_with_cert_and_key_paths(cert_path, key_path) "
        "instead; deploy the cert.pem + key.pem files to the device's "
        "/lib/ (or /) directory and pass their paths.",
    )


def ssl_context_with_cert_and_key_paths(cert_path, key_path):
    """Build a CP server-side SSLContext from cert and key file paths."""
    import ssl  # noqa: PLC0415

    context = ssl.create_default_context()
    # CP's mbedTLS binding requires this empty-cadata call before load_cert_chain.
    context.load_verify_locations(cadata="")
    context.load_cert_chain(cert_path, key_path)
    return context


def ssl_context_with_ca(ca_pem):
    """Build a CP SSLContext that trusts *ca_pem* (PEM only).

    Raises:
        ValueError: The input is not PEM (DER is not accepted on CircuitPython).
    """
    # Validate before importing ssl, which is absent on the CP unix-port.
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
    # CP's GC is non-compacting; drop the buffer and collect so the span is reused.
    del ca_pem
    gc.collect()
    return context


def ssl_context_no_verify():
    """Return a CP ``ssl.SSLContext`` that skips certificate verification."""
    import ssl  # noqa: PLC0415

    context = ssl.create_default_context()
    # CP has no settable verify_mode; empty cadata disables verification at handshake.
    context.load_verify_locations(cadata="")
    context.check_hostname = False
    return context


def connector(host, port, *, tls=False, context=None, radio=None):
    """Return a tick-driven connector for CircuitPython."""
    return _CPConnector(host, port, tls=tls, context=context, radio=radio)


class _CPConnector(SocketConnector):
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
                # Assign before wrap_socket so _fail() closes the raw socket if wrapping raises.
                self.socket = sock
                if self._tls:
                    self._context = _resolve_default_context(self._context)
                    sock = self._context.wrap_socket(
                        sock, server_hostname=self._host,
                    )
                    self.socket = sock  # rebind so _fail closes the wrapper
                # Blocking connect: completes TCP and, if wrapped, the TLS handshake.
                sock.connect(self.sockaddr)
                self.state = STATE_READY
                return
        except Exception as error:  # noqa: BLE001 - any failure stops the machine
            self._fail(error)


# Collect import-time scratch so the first lazy-load allocation lands in a cleaner heap.
gc.collect()
