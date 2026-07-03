"""CPython adapter — stdlib ``socket`` + ``ssl``.

Used:

* on CPython directly (host-side tests, sim runs, downstream libs
  imported on a laptop without a board);
* as the test substrate for ``FakeSocket`` conformance — passing
  tests here prove the contract every other adapter implements.

``socket.create_connection`` does the dial-and-connect and raises
:class:`OSError` on failure.  TLS uses ``ssl.SSLContext.wrap_socket``;
``context=None`` means ``ssl.create_default_context()``.
"""

#: Source bundle only; never lands on a device.
__chumicro_runtimes__ = ("cpython",)

import select
import socket
import ssl

from chumicro_sockets._connector import (
    _TERMINAL,
    STATE_AWAITING_DNS,
    STATE_AWAITING_TCP,
    STATE_AWAITING_TLS,
    STATE_READY,
    SocketConnector,
)


def connect_tcp(host, port, **_kwargs):
    """Open a plain TCP connection.

    Returns a real :class:`socket.socket` — its ``send`` /
    ``recv_into`` / ``close`` / ``setblocking`` / ``settimeout``
    surface is a superset of what downstream libs require, so no
    wrapper is needed.
    """
    return socket.create_connection((host, port))


def connect_tls(host, port, *, context=None, **_kwargs):
    """Open a TLS connection.

    *context=None* uses :func:`ssl.create_default_context` — system
    default CA bundle, hostname check enabled, modern cipher defaults.
    Pass a pre-configured context for custom CAs / mTLS / pinned
    cipher suites.
    """
    raw = socket.create_connection((host, port))
    return _resolve_default_context(context).wrap_socket(raw, server_hostname=host)


def _resolve_default_context(context):
    """Return *context* unchanged, or build CPython's default context if ``None``.

    Uses :func:`ssl.create_default_context`, which validates against
    the host OS trust store and turns on every secure default.
    """
    return context if context is not None else ssl.create_default_context()


def tcp_connector(host, port, **_kwargs):
    """Return a non-blocking TCP :class:`SocketConnector` for CPython.

    Uses stdlib ``socket.getaddrinfo`` + non-blocking ``socket.connect``
    (``BlockingIOError`` / EINPROGRESS, then ``select.select`` for
    writability + ``SO_ERROR`` for the connect outcome) for a truly
    per-tick non-blocking dial.
    """
    return _CPythonConnector(host, port, tls=False, context=None)


def tls_connector(host, port, *, context=None, **_kwargs):
    """Return a non-blocking TLS :class:`SocketConnector` for CPython.

    Same shape as :func:`tcp_connector` plus a TLS handshake phase
    driven by ``ssl.SSLContext.wrap_socket(do_handshake_on_connect=False)``
    + ``sock.do_handshake()`` looped across ticks until done.
    *context=None* uses :func:`ssl.create_default_context`.
    """
    return _CPythonConnector(host, port, tls=True, context=context)


class _CPythonConnector(SocketConnector):
    """CPython non-blocking dialer — three genuine per-tick phases.

    The state progression matches the base class's vocabulary:
    ``awaiting_dns`` → ``awaiting_tcp`` → (optional ``awaiting_tls``)
    → ``ready``.  Each ``tick`` advances one step; the TCP and TLS
    steps return early (no state change) when the kernel hasn't
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
            pass  # Expected — connect is in progress.
        return sock

    def _tcp_ready(self, sock):
        # ``SO_ERROR`` alone is unreliable right after a non-blocking
        # connect on macOS (reads 0 mid-flight).  Wait for writability
        # via ``select.select`` first; once writable, ``SO_ERROR`` is
        # the connect outcome (0 = connected, non-zero = errno).
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
        try:
            sock.do_handshake()
        except (ssl.SSLWantReadError, ssl.SSLWantWriteError):
            return False
        return True


def listen_tcp(host, port, *, backlog=4, **_kwargs):
    """Open a non-blocking TCP listening socket.

    Returns a real :class:`socket.socket` set to non-blocking mode and
    bound + listening on (*host*, *port*).  Already satisfies the
    ``ListeningSocket`` structural protocol — :meth:`socket.accept`
    returns ``(socket, address)`` and raises ``OSError(EAGAIN)`` when
    no connection is queued.

    ``SO_REUSEADDR`` is set so a quick restart of the server doesn't
    trip ``OSError(EADDRINUSE)`` on the rebind.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((host, port))
    sock.listen(backlog)
    sock.setblocking(False)
    return sock


def ssl_context_with_cert_and_key(cert_pem, key_pem):
    """Build a server-side SSLContext that presents *cert_pem* signed by *key_pem*.

    Mirrors the client-side `ssl_context_with_ca` shape but loads a
    *cert chain* + *private key* via `SSLContext.load_cert_chain`
    (rather than a *trust store*).  The context is suitable for
    `wrap_socket(..., server_side=True)` calls.

    *cert_pem* and *key_pem* are PEM-encoded bytes / str.  CPython's
    `load_cert_chain` accepts file paths only (not in-memory bytes),
    so we write them to a temporary file and load from there.
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
        # ``load_cert_chain`` reads the PEM material into the context, so
        # the temp files are no longer needed.  Remove them whether it
        # succeeded or raised — ``delete=False`` above means they'd
        # otherwise accumulate in the temp dir forever (private keys
        # included).
        for path in (cert_path, key_path):
            if path is not None:
                try:
                    os.unlink(path)
                except OSError:
                    pass
    return context


def listen_tls(host, port, *, context, backlog=4, **_kwargs):
    """Open a non-blocking TLS listening socket on CPython.

    Returns a wrapper whose `accept()` returns a `(tls_wrapped_client,
    address)` tuple — the TLS handshake happens synchronously inside
    `accept()`.  Per-runtime contract documented in the public
    `tls_listening_socket` factory.
    """
    raw_listener = listen_tcp(host, port, backlog=backlog)
    return _CPythonTLSListenerWrapper(raw_listener, context)


class _CPythonTLSListenerWrapper:
    """Wraps a raw CPython listener so accept() yields TLS sockets.

    The TLS handshake runs inside `accept()` after the TCP `accept()`
    returns the new client.  On a non-blocking listener the underlying
    `accept()` raises `BlockingIOError` when no client is queued; we
    propagate that as `OSError(EAGAIN)`.

    Holds the raw listening socket on ``sock`` so Runner reads the
    underlying registrable listener via the connector's ``io_socket``
    (Runner uses ``getattr(io_socket, "sock", io_socket)``).
    """

    def __init__(self, raw_listener, context):
        self.sock = raw_listener
        self._context = context

    def accept(self):  # pragma: no cover - exercised by slice 7t live test
        client_raw, address = self.sock.accept()
        # `wrap_socket(..., server_side=True)` performs the TLS
        # handshake synchronously.  Set the underlying socket to
        # blocking for the handshake (mbedTLS doesn't support
        # async handshake on the server side cleanly), then back
        # to non-blocking for the application traffic.
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

    Returns a :class:`_CPythonUDPWrapper` so the public ``sendto(data,
    host, port)`` separated-arg shape is honored (stdlib expects a
    ``(host, port)`` tuple).
    """
    import socket  # noqa: PLC0415 - runtime-gated

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    if broadcast:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.bind((bind_host, bind_port))
    return _CPythonUDPWrapper(sock)


class _CPythonUDPWrapper:
    """Adapts a CPython ``socket.socket`` to the chumicro_sockets UDP protocol.

    Normalizes ``sendto`` to the separated ``(data, host, port)``
    signature and ``recvfrom_into`` to the ``(nbytes, (host, port))``
    return tuple.
    """

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
    """Build an SSLContext that trusts only the CA(s) in *ca_pem*.

    Uses :meth:`ssl.SSLContext.load_verify_locations` with the PEM
    bytes — stdlib accepts a string or bytes via ``cadata``, so we
    pass either form through unchanged.  The context inherits
    ``ssl.create_default_context``'s ``CERT_REQUIRED`` +
    ``check_hostname=True`` defaults; only the trust anchor is
    replaced.  Override on the returned context if needed.
    """
    import ssl  # noqa: PLC0415 - runtime-gated

    context = ssl.create_default_context()
    if isinstance(ca_pem, str):
        context.load_verify_locations(cadata=ca_pem)
    else:
        raw = bytes(ca_pem)
        if b"-----BEGIN CERTIFICATE-----" in raw:
            # PEM bytes — stdlib wants ``cadata`` as str for PEM.
            context.load_verify_locations(cadata=raw.decode("ascii"))
        elif raw[:1] == b"\x30":
            # DER (ASN.1 SEQUENCE) — stdlib accepts bytes-like cadata
            # as DER directly.
            context.load_verify_locations(cadata=raw)
        else:
            raise ValueError(
                "ssl_context_with_ca expects PEM "
                "(-----BEGIN CERTIFICATE-----) or DER (ASN.1 SEQUENCE, "
                "first byte 0x30) — got neither",
            )
    return context


def ssl_context_no_verify():
    """Return a CPython ``ssl.SSLContext`` that **skips** verification.

    Explicit opt-out for callers that intentionally don't want to
    validate the peer.  Named so code reviewers can grep for it —
    ``tls_client_socket(host, port, context=ssl_context_no_verify())``
    shouts what it does.

    Inverts both of ``ssl.create_default_context``'s secure defaults:
    ``check_hostname = False`` (must come first — stdlib refuses to
    set ``verify_mode = CERT_NONE`` while ``check_hostname`` is true)
    and ``verify_mode = CERT_NONE``.
    """
    import ssl  # noqa: PLC0415 - runtime-gated

    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    return context
