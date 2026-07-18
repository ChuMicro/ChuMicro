"""MicroPython adapter: stdlib ``socket`` plus ``ssl`` (mbedTLS-backed)."""

__chumicro_runtimes__ = ("micropython",)

import binascii
import errno
import gc
import select
import socket

from chumicro_sockets._connector import (
    _TERMINAL,
    STATE_AWAITING_DNS,
    STATE_AWAITING_TCP,
    STATE_AWAITING_TLS,
    STATE_READY,
    SocketConnector,
)


def _no_op(*_args, **_kwargs):
    return None


class _MpSocketWrapper:
    def __init__(self, sock):
        self.sock = sock
        self.send = sock.send
        self.close = sock.close
        self.setblocking = sock.setblocking
        # mbedTLS SSLSocket has no settimeout; fall back to a no-op.
        self.settimeout = getattr(sock, "settimeout", _no_op)

    def recv_into(self, buffer, nbytes=0):
        """Read into *buffer* via MP's stream ``readinto``."""
        size = min(nbytes, len(buffer)) if nbytes > 0 else len(buffer)
        copied = self.sock.readinto(buffer, size)
        if copied is None:
            # MP readinto returns None on a would-block; raise EAGAIN to hold the recv contract.
            raise OSError(errno.EAGAIN, "would block")
        return copied


def _resolve_default_context(context):  # pragma: no cover - device only
    if context is not None:
        return context
    global _DEFAULT_CONTEXT_CACHE
    if _DEFAULT_CONTEXT_CACHE is not None:
        return _DEFAULT_CONTEXT_CACHE
    if _OVERRIDE_PEM is not None:
        _DEFAULT_CONTEXT_CACHE = ssl_context_with_ca(_OVERRIDE_PEM)
        return _DEFAULT_CONTEXT_CACHE
    from chumicro_sockets import (
        _ca_bundle,  # noqa: PLC0415 - data-file loader; only TLS-using paths reach it
    )

    _DEFAULT_CONTEXT_CACHE = ssl_context_with_ca(_ca_bundle.read_der())
    return _DEFAULT_CONTEXT_CACHE


def udp_socket(  # pragma: no cover - device only
    *,
    bind_host="0.0.0.0",
    bind_port=0,
    broadcast=False,
    **_kwargs,
):
    """Open a UDP socket on MicroPython, bound to (bind_host, bind_port)."""
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
    def __init__(self, sock):
        self.sock = sock
        self.close = sock.close
        self.setblocking = sock.setblocking
        self.settimeout = sock.settimeout
        # Bare-metal MP ports lack getsockname (the unix build has it); forward only when present.
        if hasattr(sock, "getsockname"):
            self.getsockname = sock.getsockname

    def sendto(self, data, host, port):
        # MP's UDP sendto wants a packed sockaddr, not a hostname; resolve via getaddrinfo.
        address_info = socket.getaddrinfo(host, port)[0]
        return self.sock.sendto(data, address_info[-1])

    def recvfrom_into(self, buffer, nbytes=0):
        size = nbytes if nbytes > 0 else len(buffer)
        result = self.sock.recvfrom(size)
        # Some MP ports return None on would-block; raise EAGAIN to match the TCP wrapper.
        if result is None:
            raise OSError(errno.EAGAIN, "would block")
        data, address = result
        copied = len(data)
        if copied:
            buffer[:copied] = data
        return copied, address


def listener(host, port, *, tls=False, context=None, backlog=4, **_kwargs):  # pragma: no cover - device only
    """Open a non-blocking TCP or TLS listening socket on MicroPython."""
    address_info = socket.getaddrinfo(host, port)[0]
    sock = socket.socket(address_info[0], address_info[1])
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    except OSError:
        # Some MP ports don't expose SO_REUSEADDR; non-fatal.
        pass
    sock.bind(address_info[-1])
    sock.listen(backlog)
    sock.setblocking(False)
    raw_listener = _MpListeningSocketWrapper(sock)
    if tls:
        return _MpTLSListenerWrapper(raw_listener, context)
    return raw_listener


class _MpListeningSocketWrapper:  # pragma: no cover - device only
    def __init__(self, sock):
        self.sock = sock
        self.close = sock.close

    def accept(self):
        """Accept a pending connection; raises ``OSError(EAGAIN)`` when none is queued."""
        new_sock, address = self.sock.accept()
        return _MpSocketWrapper(new_sock), address

    def setblocking(self, flag):
        self.sock.setblocking(flag)


def ssl_context_with_cert_and_key(cert_pem, key_pem):  # pragma: no cover - device only
    """Build an MP server-side SSLContext from in-memory cert and key."""
    import ssl  # noqa: PLC0415

    if isinstance(cert_pem, str):
        cert_pem = cert_pem.encode("ascii")
    if isinstance(key_pem, str):
        key_pem = key_pem.encode("ascii")
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert_pem, key_pem)
    # Drop the PEM buffers and collect before the caller's next allocation.
    del cert_pem, key_pem
    gc.collect()
    return context


class _MpTLSListenerWrapper:  # pragma: no cover - device only
    def __init__(self, raw_listener, context):
        self.sock = raw_listener
        self._context = context

    def accept(self):
        new_wrapper, address = self.sock.accept()
        # The handshake needs the raw MP socket, not the _MpSocketWrapper polyfill.
        underlying = new_wrapper.sock
        underlying.setblocking(True)
        try:
            tls_sock = self._context.wrap_socket(underlying, server_side=True)
        except Exception:
            underlying.close()
            raise
        # Revert to non-blocking after the handshake so the data path sees EAGAIN.
        try:
            tls_sock.setblocking(False)
        except (OSError, AttributeError):
            pass
        return _MpSocketWrapper(tls_sock), address

    def close(self):
        self.sock.close()

    def setblocking(self, flag):
        self.sock.setblocking(flag)


def ssl_context_with_ca(ca_pem):  # pragma: no cover - device only
    """Build an MP ``ssl.SSLContext`` that trusts only *ca_pem* (PEM or DER).

    Args:
        ca_pem: PEM or DER CA bundle as bytes, str, or bytearray.

    Raises:
        ValueError: The input is neither PEM nor DER-shaped.
    """
    import ssl  # noqa: PLC0415

    if isinstance(ca_pem, str):
        ca_pem = ca_pem.encode("ascii")
    elif not isinstance(ca_pem, bytes):
        ca_pem = bytes(ca_pem)  # bytearray / memoryview

    if b"-----BEGIN CERTIFICATE-----" in ca_pem:
        # a2b_base64 skips whitespace, so no per-line strip is needed. cadata is wrapped
        # in bytes() at load time: rp2's load_verify_locations rejects a bytearray.
        begin_marker = b"-----BEGIN CERTIFICATE-----"
        end_marker = b"-----END CERTIFICATE-----"
        source = memoryview(ca_pem)
        cadata = bytearray()
        search_from = 0
        while True:
            begin_at = ca_pem.find(begin_marker, search_from)
            if begin_at < 0:
                break
            body_start = begin_at + len(begin_marker)
            end_at = ca_pem.find(end_marker, body_start)
            if end_at < 0:
                break
            cadata += binascii.a2b_base64(source[body_start:end_at])
            search_from = end_at + len(end_marker)
    elif ca_pem[:1] == b"\x30":  # ASN.1 SEQUENCE, already DER
        cadata = ca_pem
    else:
        raise ValueError(
            "ssl_context_with_ca expects PEM "
            "(-----BEGIN CERTIFICATE-----) or DER (ASN.1 SEQUENCE, "
            "first byte 0x30); got neither",
        )

    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.load_verify_locations(cadata=bytes(cadata))
    context.verify_mode = ssl.CERT_REQUIRED
    # MP's GC is non-compacting; drop the ~16 KB buffers and collect so the span is reused.
    del cadata, ca_pem
    gc.collect()
    return context


# None means use the library-shipped bundle.
_OVERRIDE_PEM = None

_DEFAULT_CONTEXT_CACHE = None


def set_default_ca_bundle(pem_bytes):
    """Replace or revert the CA bundle used by ``connector(tls=True, context=None)``."""
    global _OVERRIDE_PEM, _DEFAULT_CONTEXT_CACHE
    _OVERRIDE_PEM = pem_bytes
    _DEFAULT_CONTEXT_CACHE = None


def ssl_context_no_verify():  # pragma: no cover - device only
    """Return an MP ``ssl.SSLContext`` that skips certificate verification."""
    import ssl  # noqa: PLC0415

    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.verify_mode = ssl.CERT_NONE
    return context


def connector(host, port, *, tls=False, context=None, **_kwargs):  # pragma: no cover - device only
    """Return a tick-driven :class:`SocketConnector` for MicroPython."""
    return _MpConnector(host, port, tls=tls, context=context)


class _MpConnector(SocketConnector):  # pragma: no cover - device only
    def __init__(self, host, port, *, tls=False, context=None):
        super().__init__(host, port, tls=tls, context=context)
        self._addr_info = None
        self._tcp_poll = None

    def tick(self, now_ms):  # noqa: ARG002 (runner contract)
        if self.state in _TERMINAL:
            return
        try:
            if self.state == STATE_AWAITING_DNS:
                self._addr_info = socket.getaddrinfo(self._host, self._port)[0]
                self.state = STATE_AWAITING_TCP
                return

            if self.state == STATE_AWAITING_TCP:
                if self.socket is None:
                    self.socket = self._issue_tcp_connect()
                    self._tcp_poll = select.poll()
                    self._tcp_poll.register(self.socket, select.POLLOUT)
                    return
                # POLLERR/POLLHUP in the mask means a refused/reset connect; SO_ERROR is unreliable on rp2.
                events = self._tcp_poll.poll(0)
                if not events:
                    return
                self._tcp_poll = None
                if events[0][1] & (select.POLLERR | select.POLLHUP):
                    raise OSError(
                        errno.ECONNREFUSED,
                        "TCP connect failed (POLLERR/POLLHUP)",
                    )
                if self._tls:
                    # wrap_socket blocks until the handshake completes; the next tick promotes to ready.
                    self._context = _resolve_default_context(self._context)
                    # The handshake needs a blocking socket; flip to blocking for it and back after.
                    raw_socket = self.socket
                    raw_socket.setblocking(True)
                    self.socket = self._context.wrap_socket(
                        raw_socket, server_hostname=self._host,
                    )
                    raw_socket.setblocking(False)
                    self.state = STATE_AWAITING_TLS
                else:
                    self.socket = _MpSocketWrapper(self.socket)
                    self.state = STATE_READY
                return

            if self.state == STATE_AWAITING_TLS:
                # wrap_socket already completed the handshake on entry; this tick just promotes.
                self.socket = _MpSocketWrapper(self.socket)
                self.state = STATE_READY
                return
        except Exception as error:  # noqa: BLE001 - any failure stops the machine
            self._fail(error)

    def _issue_tcp_connect(self):
        sock = socket.socket(self._addr_info[0], self._addr_info[1])
        sock.setblocking(False)
        try:
            sock.connect(self._addr_info[-1])
        except OSError as connect_exception:
            # MP's non-blocking connect raises EINPROGRESS; its value differs per lwIP port,
            # so compare against errno.EINPROGRESS, not a literal.
            if connect_exception.errno != errno.EINPROGRESS:
                sock.close()
                raise
        return sock

# Collect import-time scratch so the first lazy-load allocation lands in a cleaner heap.
gc.collect()
