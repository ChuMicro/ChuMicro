"""MicroPython adapter: stdlib ``socket`` plus ``ssl`` (mbedTLS-backed).

One adapter covers every supported port (MP 1.26+ ships ``MICROPY_SSL_MBEDTLS``
on both ESP32 and RP2). MP's lwIP socket exposes stream ``readinto`` but not
``recv_into``, so :class:`_MpSocketWrapper` polyfills ``recv_into`` on top of it.
TLS always passes *host* as ``server_hostname`` (SNI-less verification breaks
against modern brokers). ``ssl`` is a lazy in-function import in every TLS-using
helper so plain-TCP consumers do not pay its ~10 KB heap cost.
"""

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
    """Adapts an MP stdlib socket to the chumicro_sockets protocol.

    MP's lwIP socket lacks ``recv_into`` but exposes the stream ``readinto``, so
    ``recv_into`` forwards to ``readinto(buffer, size)``, filling the buffer in
    place with no per-receive ``bytes`` allocation. One path covers plain TCP and
    the mbedTLS ``SSLSocket``, which also exposes ``readinto``.
    """

    def __init__(self, sock):
        self.sock = sock
        # Forward the operations MP supports natively so callers skip a Python
        # shim; send / close / setblocking exist on plain and TLS sockets.
        self.send = sock.send
        self.close = sock.close
        self.setblocking = sock.setblocking
        # mbedTLS SSLSocket has no settimeout; fall back to a no-op so the
        # wrapper surface is uniform across plain TCP and TLS.
        self.settimeout = getattr(sock, "settimeout", _no_op)

    def recv_into(self, buffer, nbytes=0):
        """Read into *buffer* via MP's stream ``readinto``.

        ``readinto(buffer, size)`` fills *buffer* in place and returns the count
        with no intermediate ``bytes``, returns 0 on a clean peer close, and
        returns ``None`` when a non-blocking read would block. We raise
        ``OSError(EAGAIN)`` on ``None`` so the "EAGAIN on no data, 0 on peer
        close" contract holds across plain TCP and TLS.
        """
        # Clamp to capacity and pass the cap as the second arg: MP's readinto
        # takes an optional max-length, so it never writes past nbytes or the end.
        size = min(nbytes, len(buffer)) if nbytes > 0 else len(buffer)
        copied = self.sock.readinto(buffer, size)
        if copied is None:
            # A non-blocking readinto with no data returns None on plain TCP and
            # MP TLS; raise the would-block errno so the recv-loop contract holds.
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
    """Open a UDP socket on MicroPython, bound to (bind_host, bind_port).

    ``recvfrom_into`` is patchy across MP ports, so the wrapper polyfills it via
    ``recvfrom`` plus a buffer copy. ``SO_BROADCAST`` is best-effort.
    """
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

    Normalizes ``sendto`` to separated ``(data, host, port)`` args and polyfills
    ``recvfrom_into`` via ``recvfrom`` plus a bytearray copy.
    """

    def __init__(self, sock):
        self.sock = sock
        self.close = sock.close
        self.setblocking = sock.setblocking
        self.settimeout = sock.settimeout
        # Bare-metal MP ports (rp2, esp32) have no getsockname (the unix build
        # does); forward it only when present.
        if hasattr(sock, "getsockname"):
            self.getsockname = sock.getsockname

    def sendto(self, data, host, port):
        # MP's UDP sendto does not auto-resolve hostnames (it wants a packed
        # sockaddr), so route through getaddrinfo as CP and CPython do. Hostname
        # callers pay one DNS lookup per sendto; tight loops should pre-resolve.
        address_info = socket.getaddrinfo(host, port)[0]
        return self.sock.sendto(data, address_info[-1])

    def recvfrom_into(self, buffer, nbytes=0):
        size = nbytes if nbytes > 0 else len(buffer)
        result = self.sock.recvfrom(size)
        # MP returns (data, address); some ports return None on would-block, so
        # raise EAGAIN explicitly to match the TCP wrapper's contract.
        if result is None:
            raise OSError(errno.EAGAIN, "would block")
        data, address = result
        copied = len(data)
        if copied:
            buffer[:copied] = data
        return copied, address


def listener(host, port, *, tls=False, context=None, backlog=4, **_kwargs):  # pragma: no cover - device only
    """Open a non-blocking TCP or TLS listening socket on MicroPython.

    ``accept()`` returns a ``(_MpSocketWrapper, address)`` tuple exposing the
    cross-runtime TCP surface. With ``tls=True`` each accepted client is
    TLS-wrapped, and the handshake runs synchronously inside ``accept()``.
    ``SO_REUSEADDR`` is best-effort.
    """
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
    """Build an MP server-side SSLContext from in-memory cert and key.

    MP's ``load_cert_chain`` accepts PEM bytes on every supported build (the
    server path enables the PEM parser, unlike ``load_verify_locations`` on rp2).
    The context targets ``PROTOCOL_TLS_SERVER``.
    """
    import ssl  # noqa: PLC0415

    if isinstance(cert_pem, str):
        cert_pem = cert_pem.encode("ascii")
    if isinstance(key_pem, str):
        key_pem = key_pem.encode("ascii")
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert_pem, key_pem)
    # mbedTLS has parsed the cert and key into its structures; drop the PEM
    # buffers and reclaim before the caller's next allocation.
    del cert_pem, key_pem
    gc.collect()
    return context


class _MpTLSListenerWrapper:  # pragma: no cover - device only
    """Wraps an MP listener so ``accept()`` yields TLS-wrapped clients. The inner
    listener stays on ``.sock`` for the poller to register.
    """

    def __init__(self, raw_listener, context):
        self.sock = raw_listener
        self._context = context

    def accept(self):
        new_wrapper, address = self.sock.accept()
        # Pull the raw MP socket out of the wrapper; the handshake needs the
        # raw socket, not the _MpSocketWrapper polyfill.
        underlying = new_wrapper.sock
        underlying.setblocking(True)
        try:
            tls_sock = self._context.wrap_socket(underlying, server_side=True)
        except Exception:
            underlying.close()
            raise
        # Revert to non-blocking after the handshake so the tick-driven recv/send
        # data path sees EAGAIN, matching the CPython TLS listener.
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
    """Build an MP ``ssl.SSLContext`` that trusts only *ca_pem*. Accepts PEM or DER.

    PEM is converted to DER inline and loaded; DER (first byte 0x30) is loaded
    as-is. Conversion is unconditional because DER is the lowest common
    denominator across MP ports (rp2's mbedTLS lacks ``MBEDTLS_PEM_PARSE_C``).
    Concatenated multi-cert bundles work. The context sets
    ``verify_mode = CERT_REQUIRED``.

    Args:
        ca_pem: PEM or DER CA bundle as bytes, str, or bytearray. Single cert or
            multi-cert bundle.

    Raises:
        ValueError: The input is neither PEM nor DER-shaped.
    """
    import ssl  # noqa: PLC0415

    if isinstance(ca_pem, str):
        ca_pem = ca_pem.encode("ascii")
    elif not isinstance(ca_pem, bytes):
        ca_pem = bytes(ca_pem)  # bytearray / memoryview

    if b"-----BEGIN CERTIFICATE-----" in ca_pem:
        # PEM to DER inline: a2b_base64 skips non-base64 bytes (newlines,
        # spaces), so no whitespace strip or per-cert list is needed, and slices
        # go through a memoryview to avoid per-region copies. cadata MUST be
        # wrapped in bytes() at the load call: rp2's load_verify_locations
        # rejects a bytearray.
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
    # mbedTLS has copied the DER into its chain; the buffers (~16 KB for the
    # shipped bundle) are dead weight now. Drop them and collect so the freed
    # span is reused rather than fragmenting (MP GC is non-compacting).
    del cadata, ca_pem
    gc.collect()
    return context


# PEM override installed via ``set_default_ca_bundle``; ``None`` means use the
# library-shipped bundle from ``chumicro_sockets._ca_bundle``.
_OVERRIDE_PEM = None

# Cache of the parsed default SSLContext; cleared when set_default_ca_bundle
# changes the trust set.
_DEFAULT_CONTEXT_CACHE = None


def set_default_ca_bundle(pem_bytes):
    """Replace or revert the CA bundle used by ``connector(tls=True, context=None)``.

    Pass ``None`` to revert to the library-shipped bundle. Passing a new bundle
    invalidates the cached default context, which the next default-context
    handshake rebuilds.
    """
    global _OVERRIDE_PEM, _DEFAULT_CONTEXT_CACHE
    _OVERRIDE_PEM = pem_bytes
    _DEFAULT_CONTEXT_CACHE = None


def ssl_context_no_verify():  # pragma: no cover - device only
    """Return an MP ``ssl.SSLContext`` that skips certificate verification.

    An explicit opt-out for callers that intentionally do not validate the peer;
    named so reviewers can grep for it. MP defaults to ``CERT_REQUIRED``, so this
    downgrades ``verify_mode`` to ``CERT_NONE``.
    """
    import ssl  # noqa: PLC0415

    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.verify_mode = ssl.CERT_NONE
    return context


def connector(host, port, *, tls=False, context=None, **_kwargs):  # pragma: no cover - device only
    """Return a tick-driven :class:`SocketConnector` for MicroPython.

    Non-blocking ``socket.connect`` (EINPROGRESS) plus ``select.poll(POLLOUT)``
    for completion. DNS and TCP are per-tick non-blocking. With ``tls=True`` the
    handshake blocks inside ``wrap_socket`` (mbedTLS exposes no non-blocking
    handshake), so ``awaiting_tls`` is a single blocking tick; application
    traffic is non-blocking afterward.
    """
    return _MpConnector(host, port, tls=tls, context=context)


class _MpConnector(SocketConnector):  # pragma: no cover - device only
    """MP non-blocking dialer: DNS and non-blocking TCP, blocking TLS.

    The public phases match the runner vocabulary, but ``awaiting_tls`` is a
    single blocking tick (mbedTLS ``wrap_socket`` runs the full handshake
    inline). The ``select.poll`` registration is built once and reused across
    ticks to stay allocation-quiet.
    """

    def __init__(self, host, port, *, tls=False, context=None):
        super().__init__(host, port, tls=tls, context=context)
        self._addr_info = None
        # Built when entering awaiting_tcp, reused across ticks, cleared on exit.
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
                # POLLOUT means the kernel resolved the connect; a refused or
                # reset connect surfaces POLLERR/POLLHUP in the same poll, so
                # check the mask and fail here (SO_ERROR is unreliable on rp2).
                events = self._tcp_poll.poll(0)  # 0 ms non-blocking probe
                if not events:
                    return
                self._tcp_poll = None
                if events[0][1] & (select.POLLERR | select.POLLHUP):
                    raise OSError(
                        errno.ECONNREFUSED,
                        "TCP connect failed (POLLERR/POLLHUP)",
                    )
                if self._tls:
                    # wrap_socket blocks until the handshake completes (a
                    # substrate limit); the next tick promotes to ready.
                    self._context = _resolve_default_context(self._context)
                    # The handshake needs a blocking socket (a non-blocking one
                    # can return mid-handshake), so flip to blocking for it and
                    # back after so the data path sees EAGAIN.
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
                # MP's ``wrap_socket`` already drove the handshake to
                # completion on entry; this tick just promotes.
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
            # MP's non-blocking connect raises EINPROGRESS; later ticks drive the
            # POLLOUT-ready check. Compare via errno.EINPROGRESS because the value
            # differs per lwIP port (115 on rp2, 119 on esp32-s2).
            if connect_exception.errno != errno.EINPROGRESS:
                sock.close()
                raise
        return sock

# Defragment compile-time scratch at module bottom so the lazy load
# from chumicro_sockets's factories lands in a cleaner heap.
gc.collect()
