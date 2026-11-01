"""``chumicro_sockets`` opens TCP, TLS, and UDP sockets the same way on CircuitPython,
MicroPython, and CPython.

``connector`` dials a server one step per ``tick`` call, ``listener`` opens a
listening socket for a server, and ``udp_socket`` opens a datagram socket.  The
``ssl_context_*`` functions build the ``context=`` those calls take for TLS.
On CircuitPython the socket calls take ``radio=wifi.radio``.  MicroPython and
CPython ignore ``radio``.
"""

import gc
import sys


class UnsupportedSSLConfigError(RuntimeError):
    """``UnsupportedSSLConfigError`` reports a TLS setup the running runtime cannot build.

    CircuitPython raises it from ``ssl_context_with_cert_and_key``, which needs
    file paths there, and from ``listener(tls=True)`` on a Pico W or Pico 2 W.
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


# Resolved lazily so import works on unix-ports that lack the socket substrate.
_adapter = None


def _get_adapter():
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
    """Return a ``SocketConnector`` that opens a TCP or TLS connection to ``host`` one step per ``tick`` call.

    The main loop calls ``connector.tick(now_ms)``, or a ``Runner`` does after
    ``runner.add(connector)``, until ``connector.state`` reads ``"ready"`` or
    ``"failed"``.  At ``"ready"``, ``connector.socket`` holds the connected
    non-blocking socket, and the caller closes it when done.  At
    ``"failed"``, ``connector.last_error`` holds the exception.
    ``connector.cancel()`` abandons a connect in progress and closes its
    socket.  ``chumicro_sockets.generators.connect`` drives the same steps
    inside a generator.

    The first ``tick`` looks up ``host`` and holds the main loop until the
    lookup returns, on every runtime.  On CircuitPython the second ``tick``
    holds the loop for the whole TCP connect and TLS handshake.  On
    MicroPython the TLS handshake holds the loop.  The connector sets no time
    limit of its own.

    Args:
        host: Server name or IP address.  With ``tls=True`` it is also the
            name checked against the server's certificate.
        port: Server port, such as ``80`` or ``443``.
        tls: ``True`` wraps the connection in TLS.
        context: ``ssl.SSLContext`` for the TLS handshake, from one of the
            ``ssl_context_*`` functions, or ``None`` to verify the server
            against the runtime's default certificate store.  That store is
            the firmware's on CircuitPython, the bundle shipped with this
            library on MicroPython, and the operating system's on CPython.
        radio: The CircuitPython radio, ``wifi.radio``, needed there on the
            first socket call.  MicroPython and CPython ignore it.

    Returns:
        A ``SocketConnector`` in the ``"awaiting_dns"`` state.  It touches the
            network on its first ``tick``.
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
    """Open a non-blocking TCP or TLS socket that listens on ``host`` and ``port``.

    ``accept()`` on the returned socket takes the next waiting client and
    returns ``(client_socket, address)``.  It raises ``OSError`` with
    ``EAGAIN`` when no client is waiting.  With ``tls=True`` on MicroPython
    and CPython, ``accept()`` holds the main loop for the client's TLS
    handshake.

    Args:
        host: Local address to listen on.  ``"0.0.0.0"`` listens on every
            interface.
        port: TCP port to listen on.
        tls: ``True`` wraps every accepted client in TLS.
        context: Server-side ``ssl.SSLContext`` from
            ``ssl_context_with_cert_and_key_paths`` or
            ``ssl_context_with_cert_and_key``.  Required with ``tls=True``.
        backlog: Number of waiting clients the network stack queues before it
            refuses more.
        radio: The CircuitPython radio, ``wifi.radio``, needed there on the
            first socket call.  MicroPython and CPython ignore it.

    Returns:
        The listening socket, with ``accept()``, ``close()``, and ``setblocking()``.

    Raises:
        ValueError: ``tls=True`` was passed without a ``context``.
        OSError: Binding or listening failed, such as when the port is in use.
        UnsupportedSSLConfigError: ``tls=True`` on CircuitPython on a Pico W or Pico 2 W.
        TypeError: The first socket call on CircuitPython got no ``radio``.
    """
    if tls and context is None:
        raise ValueError(
            "listener(tls=True) requires a server-side context=; build "
            "one via ssl_context_with_cert_and_key(_paths)",
        )
    return _get_adapter().listener(
        host, port, tls=tls, context=context, backlog=backlog, radio=radio,
    )


def ssl_context_with_cert_and_key(
    cert_pem: str | bytes,
    key_pem: str | bytes,
) -> object:
    """Build a server-side ``ssl.SSLContext`` from a certificate and private key held in memory.

    ``listener(tls=True, context=...)`` takes the result.  CircuitPython loads
    a certificate only from files, so this function raises there.
    ``ssl_context_with_cert_and_key_paths`` works on every runtime.

    Args:
        cert_pem: PEM text of the server certificate, or of a certificate chain.
        key_pem: PEM text of the private key that matches ``cert_pem``.

    Returns:
        The ``ssl.SSLContext``.

    Raises:
        UnsupportedSSLConfigError: Called on CircuitPython.
    """
    return _get_adapter().ssl_context_with_cert_and_key(cert_pem, key_pem)


def ssl_context_with_cert_and_key_paths(
    cert_path: str,
    key_path: str,
) -> object:
    """Build a server-side ``ssl.SSLContext`` from certificate and key files on the board.

    ``listener(tls=True, context=...)`` takes the result.  It works on every
    runtime.  On MicroPython it reads both files into memory first.

    Args:
        cert_path: Path to the PEM certificate file, such as ``"/cert.pem"``.
        key_path: Path to the PEM private-key file.

    Returns:
        The ``ssl.SSLContext``.

    Raises:
        OSError: A file is missing or unreadable.
    """
    adapter = _get_adapter()
    if hasattr(adapter, "ssl_context_with_cert_and_key_paths"):
        return adapter.ssl_context_with_cert_and_key_paths(cert_path, key_path)
    with open(cert_path, "rb") as cert_handle:
        cert_bytes = cert_handle.read()
    with open(key_path, "rb") as key_handle:
        key_bytes = key_handle.read()
    context = adapter.ssl_context_with_cert_and_key(cert_bytes, key_bytes)
    # Drop the PEM buffers and collect before the caller's next allocation.
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
    """Open a UDP socket bound to ``bind_host`` and ``bind_port``, and return it.

    ``sendto(data, host, port)`` sends one datagram and takes the host and
    port as two arguments.  ``recvfrom_into(buffer, nbytes=0)`` receives one
    and returns ``(count, address)``.  The socket starts in blocking mode,
    where ``recvfrom_into`` holds the main loop until a datagram arrives.
    After ``setblocking(False)`` it raises ``OSError`` with ``EAGAIN``
    instead.

    Args:
        bind_host: Local address to bind.  ``"0.0.0.0"`` binds every interface.
        bind_port: Local port.  ``0`` picks a free port.
        radio: The CircuitPython radio, ``wifi.radio``, needed there on the
            first socket call.  MicroPython and CPython ignore it.
        broadcast: ``True`` allows ``sendto`` to a broadcast address such as
            ``"255.255.255.255"``.  A CircuitPython or MicroPython build
            without the option ignores it.

    Raises:
        OSError: Binding failed, such as when the port is in use.
        TypeError: The first socket call on CircuitPython got no ``radio``.
    """
    return _get_adapter().udp_socket(
        bind_host=bind_host,
        bind_port=bind_port,
        radio=radio,
        broadcast=broadcast,
    )


def ssl_context_with_ca(ca_pem: str | bytes) -> object:
    """Build a client ``ssl.SSLContext`` that trusts the certificate authorities in ``ca_pem``.

    ``connector(tls=True, context=...)`` takes the result, to reach a server
    whose certificate a private or self-signed authority issued.

    Args:
        ca_pem: One or more CA certificates.  PEM text works on every runtime.
            DER ``bytes`` work on MicroPython and CPython.

    Returns:
        The ``ssl.SSLContext``.

    Raises:
        ValueError: ``ca_pem`` holds neither PEM nor DER.  CircuitPython also
            raises it for DER.
    """
    return _get_adapter().ssl_context_with_ca(ca_pem)


def ssl_context_no_verify() -> object:
    """Return a client ``ssl.SSLContext`` that accepts any server certificate.

    The connection stays encrypted, and any server can pose as the ``host``
    it dials.

    Returns:
        The ``ssl.SSLContext``.
    """
    return _get_adapter().ssl_context_no_verify()


def set_default_ca_bundle(pem_bytes: bytes | str | None) -> None:
    """Replace the certificate authorities that ``connector(tls=True, context=None)`` trusts on MicroPython.

    On MicroPython this library ships a bundle of root certificates, and
    ``None`` restores it.  The change applies to every TLS handshake that
    starts after the call.  CircuitPython uses the firmware's store and
    CPython the operating system's, so the call does nothing there.

    Args:
        pem_bytes: CA certificates as PEM text or DER bytes, or ``None`` for
            the shipped bundle.
    """
    adapter = _get_adapter()
    if hasattr(adapter, "set_default_ca_bundle"):
        adapter.set_default_ca_bundle(pem_bytes)


# Collect import-time scratch so the consumer's first allocation lands in a cleaner heap.
gc.collect()
