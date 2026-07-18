"""CPython adapter: stdlib ``socket`` plus ``ssl``.

Runs on CPython directly (host-side tests, sim runs, downstream libraries on a
laptop) and serves as the conformance substrate whose passing tests prove the
contract every other adapter implements. ``connector`` dials via a genuinely
non-blocking per-tick state machine.
"""

#: Source bundle only; never lands on a device.
__chumicro_runtimes__ = ("cpython",)

import errno
import select
import socket
import ssl

from chumicro_sockets._connector import (
    _IO_READ,
    _IO_WRITE,
    _TERMINAL,
    STATE_AWAITING_DNS,
    STATE_AWAITING_TCP,
    STATE_AWAITING_TLS,
    STATE_READY,
    SocketConnector,
)


class _CPythonTLSSocketWrapper:
    """Translates a CPython ``ssl.SSLSocket``'s ``SSLWant*`` would-block into
    ``OSError(EAGAIN)`` on ``recv`` / ``recv_into`` / ``send``, so TLS sees the
    same data-path contract as plain TCP. The raw ``SSLSocket`` stays on
    ``.sock`` for the poller to register.
    """

    def __init__(self, sock):
        self.sock = sock
        # close / setblocking / settimeout need no translation; forward them.
        self.close = sock.close
        self.setblocking = sock.setblocking
        self.settimeout = sock.settimeout

    def recv_into(self, buffer, nbytes=0):
        try:
            if nbytes:
                return self.sock.recv_into(buffer, nbytes)
            return self.sock.recv_into(buffer)
        except (ssl.SSLWantReadError, ssl.SSLWantWriteError):
            raise OSError(errno.EAGAIN, "would block") from None

    def recv(self, nbytes):
        try:
            return self.sock.recv(nbytes)
        except (ssl.SSLWantReadError, ssl.SSLWantWriteError):
            raise OSError(errno.EAGAIN, "would block") from None

    def send(self, data):
        try:
            return self.sock.send(data)
        except (ssl.SSLWantReadError, ssl.SSLWantWriteError):
            raise OSError(errno.EAGAIN, "would block") from None


def _resolve_default_context(context):
    return context if context is not None else ssl.create_default_context()


def connector(host, port, *, tls=False, context=None, **_kwargs):
    """Return a non-blocking :class:`SocketConnector` for CPython.

    Three genuine per-tick phases: non-blocking ``socket.connect`` (EINPROGRESS,
    then ``select`` for writability and ``SO_ERROR`` for the outcome), then an
    optional TLS handshake looped across ticks via ``do_handshake()``.
    ``context=None`` uses the host OS trust store.
    """
    return _CPythonConnector(host, port, tls=tls, context=context)


class _CPythonConnector(SocketConnector):
    """CPython non-blocking dialer: three genuine per-tick phases.

    ``awaiting_dns`` to ``awaiting_tcp`` to optional ``awaiting_tls`` to
    ``ready``; the TCP and TLS steps return early when the kernel has not
    finished the in-flight operation yet.
    """

    def __init__(self, host, port, *, tls=False, context=None):
        super().__init__(host, port, tls=tls, context=context)
        self._addr_info = None

    def tick(self, now_ms):  # noqa: ARG002 (runner contract)
        if self.state in _TERMINAL:
            return
        try:
            if self.state == STATE_AWAITING_DNS:
                self._addr_info = socket.getaddrinfo(
                    self._host, self._port, type=socket.SOCK_STREAM,
                )[0]
                self.state = STATE_AWAITING_TCP
                return

            if self.state == STATE_AWAITING_TCP:
                if self.socket is None:
                    self.socket = self._issue_tcp_connect()
                    return
                if not self._tcp_ready(self.socket):
                    return
                if self._tls:
                    self.socket = self._wrap_tls(self.socket)
                    self.state = STATE_AWAITING_TLS
                else:
                    self.state = STATE_READY
                return

            if self.state == STATE_AWAITING_TLS:
                if not self._tls_ready(self.socket):
                    return
                # Handshake done: wrap so the ready socket reports EAGAIN, not
                # ssl.SSLWant*, on a would-block.
                self.socket = _CPythonTLSSocketWrapper(self.socket)
                self.state = STATE_READY
                return
        except Exception as error:  # noqa: BLE001 - any failure stops the machine
            self._fail(error)

    def _issue_tcp_connect(self):
        af, socktype, proto, _, sockaddr = self._addr_info
        sock = socket.socket(af, socktype, proto)
        sock.setblocking(False)
        try:
            sock.connect(sockaddr)
        except BlockingIOError:
            pass  # Expected: connect is in progress.
        return sock

    def _tcp_ready(self, sock):
        # SO_ERROR alone is unreliable right after a non-blocking connect on
        # macOS; wait for writability first, then SO_ERROR is the outcome.
        _, writable, _ = select.select([], [sock], [], 0)
        if sock not in writable:
            return False
        connect_errno = sock.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)
        if connect_errno != 0:
            raise OSError(connect_errno, "TCP connect failed")
        return True

    def _wrap_tls(self, sock):
        return _resolve_default_context(self._context).wrap_socket(
            sock, server_hostname=self._host, do_handshake_on_connect=False,
        )

    def _tls_ready(self, sock):
        # Each SSLWant* names the one direction the handshake is blocked on;
        # recording it lets io_interest drop the other bit, so an always-writable
        # socket does not busy-wake the poller during the WantRead-heavy handshake.
        try:
            sock.do_handshake()
        except ssl.SSLWantReadError:
            self._tls_interest = _IO_READ
            return False
        except ssl.SSLWantWriteError:
            self._tls_interest = _IO_WRITE
            return False
        return True


def listener(host, port, *, tls=False, context=None, backlog=4, **_kwargs):
    """Open a non-blocking TCP or TLS listening socket on CPython.

    Plain TCP returns a non-blocking :class:`socket.socket`; ``accept()`` returns
    ``(socket, address)`` and raises ``OSError(EAGAIN)`` when nothing is queued.
    With ``tls=True`` the listener is wrapped so ``accept()`` returns a TLS client
    after a synchronous handshake. ``SO_REUSEADDR`` is set so a quick restart
    does not trip ``EADDRINUSE``.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((host, port))
    sock.listen(backlog)
    sock.setblocking(False)
    if tls:
        return _CPythonTLSListenerWrapper(sock, context)
    return sock


def ssl_context_with_cert_and_key(cert_pem, key_pem):
    """Build a server-side SSLContext presenting *cert_pem* signed by *key_pem*.

    CPython's ``load_cert_chain`` accepts file paths only, so this writes the PEM
    material to temp files, loads it, then removes them. The context targets
    ``PROTOCOL_TLS_SERVER``.
    """
    import os  # noqa: PLC0415 - runtime-gated
    import ssl  # noqa: PLC0415 - runtime-gated
    import tempfile  # noqa: PLC0415 - runtime-gated

    if isinstance(cert_pem, (bytes, bytearray)):
        cert_pem_text = bytes(cert_pem).decode("ascii")
    else:
        cert_pem_text = cert_pem
    if isinstance(key_pem, (bytes, bytearray)):
        key_pem_text = bytes(key_pem).decode("ascii")
    else:
        key_pem_text = key_pem
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    cert_path = None
    key_path = None
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".cert.pem", delete=False,
    ) as cert_handle:
        cert_handle.write(cert_pem_text)
        cert_path = cert_handle.name
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".key.pem", delete=False,
    ) as key_handle:
        key_handle.write(key_pem_text)
        key_path = key_handle.name
    try:
        context.load_cert_chain(certfile=cert_path, keyfile=key_path)
    finally:
        # load_cert_chain has read the PEM into the context; remove the temp
        # files whether it succeeded or raised (delete=False, and one is a key).
        for path in (cert_path, key_path):
            if path is not None:
                try:
                    os.unlink(path)
                except OSError:
                    pass
    return context


class _CPythonTLSListenerWrapper:
    """Wraps a raw CPython listener so ``accept()`` runs the TLS handshake and
    returns a TLS client. ``BlockingIOError`` (no client queued) surfaces as
    ``OSError(EAGAIN)``. The raw listener stays on ``.sock`` for the poller.
    """

    def __init__(self, raw_listener, context):
        self.sock = raw_listener
        self._context = context

    def accept(self):  # pragma: no cover - exercised by slice 7t live test
        client_raw, address = self.sock.accept()
        # wrap_socket(server_side=True) runs the handshake synchronously and
        # needs a blocking socket, so flip to blocking for it and back after.
        client_raw.setblocking(True)
        try:
            wrapped = self._context.wrap_socket(client_raw, server_side=True)
        except Exception:
            client_raw.close()
            raise
        wrapped.setblocking(False)
        return wrapped, address

    def close(self):
        self.sock.close()

    def setblocking(self, flag):  # pragma: no cover - listener already non-blocking
        self.sock.setblocking(flag)

    def getsockname(self):  # pragma: no cover - inspection-only
        return self.sock.getsockname()


def udp_socket(*, bind_host="0.0.0.0", bind_port=0, broadcast=False, **_kwargs):
    """Open a UDP socket on CPython, bound to (bind_host, bind_port).

    Wraps the stdlib socket so ``sendto`` takes separated ``(data, host, port)``
    args instead of stdlib's ``(host, port)`` tuple.
    """
    import socket  # noqa: PLC0415 - runtime-gated

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    if broadcast:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.bind((bind_host, bind_port))
    return _CPythonUDPWrapper(sock)


class _CPythonUDPWrapper:
    def __init__(self, sock):
        self.sock = sock
        self.close = sock.close
        self.setblocking = sock.setblocking
        self.settimeout = sock.settimeout
        self.getsockname = sock.getsockname

    def sendto(self, data, host, port):
        return self.sock.sendto(data, (host, port))

    def recvfrom_into(self, buffer, nbytes=0):
        size = nbytes if nbytes > 0 else len(buffer)
        view = memoryview(buffer)[:size]
        nbytes_received, address = self.sock.recvfrom_into(view, size)
        return nbytes_received, address


def ssl_context_with_ca(ca_pem):
    """Build a CPython SSLContext that trusts only the CA(s) in *ca_pem*.

    Accepts PEM (``str`` or ``bytes``) or DER (``bytes``, first byte 0x30) via
    ``load_verify_locations``, and raises ``ValueError`` for anything else. Keeps
    ``create_default_context``'s ``CERT_REQUIRED`` + ``check_hostname=True``
    defaults, replacing only the trust anchor.
    """
    import ssl  # noqa: PLC0415 - runtime-gated

    context = ssl.create_default_context()
    if isinstance(ca_pem, str):
        context.load_verify_locations(cadata=ca_pem)
    else:
        raw = bytes(ca_pem)
        if b"-----BEGIN CERTIFICATE-----" in raw:
            # PEM bytes: stdlib wants cadata as str for PEM.
            context.load_verify_locations(cadata=raw.decode("ascii"))
        elif raw[:1] == b"\x30":
            # DER (ASN.1 SEQUENCE): stdlib accepts bytes-like cadata as DER.
            context.load_verify_locations(cadata=raw)
        else:
            raise ValueError(
                "ssl_context_with_ca expects PEM "
                "(-----BEGIN CERTIFICATE-----) or DER (ASN.1 SEQUENCE, "
                "first byte 0x30); got neither",
            )
    return context


def ssl_context_no_verify():
    """Return a CPython ``ssl.SSLContext`` that skips verification.

    An explicit opt-out for callers that intentionally do not validate the peer;
    named so reviewers can grep for it. Sets ``check_hostname = False`` first
    (stdlib refuses ``CERT_NONE`` while it is true), then
    ``verify_mode = CERT_NONE``.
    """
    import ssl  # noqa: PLC0415 - runtime-gated

    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    return context
