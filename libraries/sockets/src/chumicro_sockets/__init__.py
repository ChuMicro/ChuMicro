"""Cross-runtime TCP, TLS, and UDP sockets for CircuitPython, MicroPython, and CPython.

The public factories (``connector``, ``listener``, ``udp_socket``) pick a
per-runtime adapter from ``sys.implementation.name``, so user code never
writes a runtime check. TLS is opt-in through ``tls=True`` plus an optional
``ssl.SSLContext``; ``context=None`` verifies against the runtime's default
trust store. Returned sockets are duck-typed: downstream libraries hold them
and call ``send`` / ``recv_into`` / ``close`` (TCP) or ``sendto`` /
``recvfrom_into`` / ``close`` (UDP) directly.
"""

import gc
import sys


class UnsupportedSSLConfigError(RuntimeError):
    """Raised when the requested TLS configuration is not supported on this runtime."""


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


# Per-package adapter cache, resolved lazily on the first factory call so
# ``import chumicro_sockets`` still works on unix-ports that lack the socket
# substrate. Tests can swap this binding to target a specific runtime.
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
    """Return a non-blocking, tick-driven TCP or TLS connector.

    The returned ``SocketConnector`` advances DNS, TCP, then optional TLS
    across repeated ``tick(now_ms)`` calls; once ``state == "ready"`` the
    connected socket is on ``connector.socket``. It exposes the runner-contract
    surface, so ``Runner.add(connector(...))`` registers it directly and
    ``chumicro_sockets.generators.connect`` can drive it from a generator.

    ``tls=True`` with ``context=None`` verifies against the runtime's default
    trust: CircuitPython's firmware CA store, CPython's host OS store, or the
    library-shipped bundle on MicroPython. DNS resolves with a synchronous
    ``getaddrinfo`` on every runtime, so passing an IP literal skips it.

    Args:
        host: DNS name or IP literal. With ``tls=True`` it is also the
            ``server_hostname`` used for SNI and certificate verification.
        port: Remote port.
        tls: ``True`` wraps the connection in TLS.
        context: SSLContext for the ``tls=True`` path. ``None`` uses the
            runtime default trust store. Ignored when ``tls=False``.
        radio: CP-only radio object (pass ``wifi.radio`` on CP boards);
            ignored on MicroPython and CPython.

    Returns:
        A ``SocketConnector`` in the ``"awaiting_dns"`` state; call ``tick``
        until it reaches ``"ready"`` or ``"failed"``.
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

    The returned listener is non-blocking: ``accept()`` returns
    ``(client_socket, address)`` when a connection is ready, or raises
    ``OSError(EAGAIN)`` when the queue is empty. With ``tls=True`` each accepted
    client is TLS-wrapped before ``accept()`` returns it, and the handshake runs
    synchronously inside ``accept()`` (on Pi Pico W class boards that can take
    100-500 ms per connection and stall the runner for that window).

    Args:
        host: Address to bind. ``"0.0.0.0"`` accepts on every interface.
        port: TCP port to bind.
        tls: ``True`` TLS-wraps every accepted client.
        context: Server-side ``ssl.SSLContext``. Required when ``tls=True``;
            ignored otherwise.
        backlog: Depth of the pending-connection queue.
        radio: CP-only radio object (pass ``wifi.radio`` on CP boards);
            ignored on MicroPython and CPython.

    Returns:
        A listening socket exposing ``accept()`` / ``close()`` /
        ``setblocking()``.

    Raises:
        ValueError: ``tls=True`` was passed without a ``context``.
        OSError: Bind or listen failed (port in use, permission denied).
        UnsupportedSSLConfigError: ``tls=True`` on CP-rp2 boards.
        TypeError: The CircuitPython runtime was invoked with ``radio=None``.
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
    """Build a server-side SSLContext from in-memory cert and key bytes.

    Presents the server's own certificate and private key to clients (the
    counterpart to :func:`ssl_context_with_ca`, which trusts a CA to verify
    someone else's certificate). Not supported on CircuitPython, whose
    ``load_cert_chain`` needs filesystem paths rather than in-memory bytes; use
    :func:`ssl_context_with_cert_and_key_paths` there.

    Args:
        cert_pem: PEM-encoded server certificate (or chain).
        key_pem: PEM-encoded private key matching the certificate.

    Returns:
        A configured :class:`ssl.SSLContext`.
    """
    return _get_adapter().ssl_context_with_cert_and_key(cert_pem, key_pem)


def ssl_context_with_cert_and_key_paths(
    cert_path: str,
    key_path: str,
) -> object:
    """Build a server-side SSLContext from cert and key files on flash.

    Works on every supported runtime, so this is the recommended API for
    CircuitPython-targeted code (CP's ``load_cert_chain`` only accepts
    filesystem paths). Still unsupported on CP-rp2 boards, where
    ``listener(tls=True)`` refuses up front.

    Args:
        cert_path: On-device path to the certificate PEM file.
        key_path: On-device path to the private-key PEM file.

    Returns:
        A configured :class:`ssl.SSLContext`.
    """
    adapter = _get_adapter()
    if hasattr(adapter, "ssl_context_with_cert_and_key_paths"):
        return adapter.ssl_context_with_cert_and_key_paths(cert_path, key_path)
    # MP and CPython: load the bytes and use the in-memory helper.
    with open(cert_path, "rb") as cert_handle:
        cert_bytes = cert_handle.read()
    with open(key_path, "rb") as key_handle:
        key_bytes = key_handle.read()
    context = adapter.ssl_context_with_cert_and_key(cert_bytes, key_bytes)
    # The context has copied the PEM in; drop the file buffers and collect
    # before the caller's next allocation.
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
    """Open a UDP datagram socket bound to (bind_host, bind_port).

    ``bind_host="0.0.0.0"`` with ``bind_port=0`` requests an ephemeral port on
    every interface. Call ``getsockname()`` on the result to learn the bound
    address when the OS chose the port.

    Args:
        bind_host: Local address to bind. ``"0.0.0.0"`` binds every interface.
        bind_port: Local port. ``0`` requests an ephemeral port.
        radio: CP-only radio object (pass ``wifi.radio`` on CP boards);
            ignored on MicroPython and CPython.
        broadcast: Set ``SO_BROADCAST`` so ``sendto`` to a broadcast address
            succeeds. Off by default; kernels reject broadcast sends without it.

    Returns: A bound UDP socket.

    Raises:
        OSError: Bind failed (port in use, permission denied).
        TypeError: The CircuitPython runtime was invoked with ``radio=None``.
    """
    return _get_adapter().udp_socket(
        bind_host=bind_host,
        bind_port=bind_port,
        radio=radio,
        broadcast=broadcast,
    )


def ssl_context_with_ca(ca_pem: str | bytes) -> object:
    """Build an SSLContext that trusts the CA(s) in *ca_pem*.

    The common "default settings except the trust anchor" recipe. Accepted
    input formats follow each runtime's ``ssl`` binding: PEM works everywhere,
    DER only on MicroPython and CPython (CircuitPython is PEM-only). Concatenated
    multi-cert bundles work on every runtime. Only the RFC 7468
    ``-----BEGIN CERTIFICATE-----`` armor is accepted; other armors (legacy
    ``X509 CERTIFICATE``, ``TRUSTED CERTIFICATE``, ``PKCS7``, bare base64) raise
    ``ValueError`` rather than silently mistrusting.

    Args:
        ca_pem: CA bundle. PEM (``str`` or ``bytes``) on every runtime; DER
            (``bytes``) on MicroPython and CPython only.

    Returns:
        A configured :class:`ssl.SSLContext`.

    Raises:
        ValueError: The input is not an accepted format for the runtime (for
            example DER on CircuitPython, or neither PEM nor DER).
    """
    return _get_adapter().ssl_context_with_ca(ca_pem)


def ssl_context_no_verify() -> object:
    """Return an SSLContext that skips certificate verification.

    An explicit opt-out for callers that intentionally do not validate the peer
    (development against self-signed brokers, captive-portal probes, smoke tests
    against untrusted hosts). Named so reviewers can grep for it; using it where
    :func:`ssl_context_with_ca` would serve is a security defect.

    Returns:
        A configured :class:`ssl.SSLContext` with verification disabled.
    """
    return _get_adapter().ssl_context_no_verify()


def set_default_ca_bundle(pem_bytes: bytes | str | None) -> None:
    """Replace or revert the CA bundle used by ``connector(tls=True, context=None)``.

    On MicroPython this swaps the library's shipped default CA bundle for a
    project-specific one (useful for a private internal CA, or a rotated public
    root the shipped set does not yet include). Pass ``None`` to revert to the
    shipped bundle. No-op on CircuitPython and CPython, which get their trust
    roots from the firmware bundle or the host OS store.

    Args:
        pem_bytes: PEM-encoded CA bundle (single or multi-cert) as bytes or
            str, or ``None`` to revert to the shipped bundle.
    """
    adapter = _get_adapter()
    if hasattr(adapter, "set_default_ca_bundle"):
        adapter.set_default_ca_bundle(pem_bytes)
    # CP and CPython get trust from elsewhere; silently ignore.


# Defragment compile-time scratch at the end of the package import so
# the consumer's first allocation lands in a cleaner heap.
gc.collect()
