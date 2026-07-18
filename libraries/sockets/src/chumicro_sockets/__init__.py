"""Cross-runtime TCP, TLS, and UDP sockets for CircuitPython, MicroPython, and CPython.

The public factories are ``connector``, ``listener``, and ``udp_socket``.
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
    """Return a non-blocking, tick-driven TCP or TLS connector.

    Args:
        host: DNS name or IP literal; also the TLS ``server_hostname`` when ``tls=True``.
        port: Remote port.
        tls: ``True`` wraps the connection in TLS.
        context: SSLContext for the ``tls=True`` path; ``None`` uses the runtime default trust store.
        radio: CP-only radio object (pass ``wifi.radio`` on CP boards); ignored elsewhere.

    Returns:
        A ``SocketConnector`` in the ``"awaiting_dns"`` state.
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

    Args:
        host: Address to bind. ``"0.0.0.0"`` accepts on every interface.
        port: TCP port to bind.
        tls: ``True`` TLS-wraps every accepted client.
        context: Server-side ``ssl.SSLContext``; required when ``tls=True``, ignored otherwise.
        backlog: Depth of the pending-connection queue.
        radio: CP-only radio object (pass ``wifi.radio`` on CP boards); ignored elsewhere.

    Returns:
        A listening socket exposing ``accept()`` / ``close()`` / ``setblocking()``.

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

    Args:
        cert_path: On-device path to the certificate PEM file.
        key_path: On-device path to the private-key PEM file.

    Returns:
        A configured :class:`ssl.SSLContext`.
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
    """Open a UDP datagram socket bound to (bind_host, bind_port).

    Args:
        bind_host: Local address to bind. ``"0.0.0.0"`` binds every interface.
        bind_port: Local port. ``0`` requests an ephemeral port.
        radio: CP-only radio object (pass ``wifi.radio`` on CP boards); ignored elsewhere.
        broadcast: Set ``SO_BROADCAST`` so ``sendto`` to a broadcast address succeeds.

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

    Args:
        ca_pem: CA bundle; PEM on every runtime, DER (``bytes``) on MicroPython and CPython only.

    Returns:
        A configured :class:`ssl.SSLContext`.

    Raises:
        ValueError: The input is not an accepted format for the runtime.
    """
    return _get_adapter().ssl_context_with_ca(ca_pem)


def ssl_context_no_verify() -> object:
    """Return an SSLContext that skips certificate verification.

    Returns:
        A configured :class:`ssl.SSLContext` with verification disabled.
    """
    return _get_adapter().ssl_context_no_verify()


def set_default_ca_bundle(pem_bytes: bytes | str | None) -> None:
    """Replace or revert the CA bundle used by ``connector(tls=True, context=None)``.

    Args:
        pem_bytes: PEM-encoded CA bundle as bytes or str, or ``None`` to revert to the shipped bundle.
    """
    adapter = _get_adapter()
    if hasattr(adapter, "set_default_ca_bundle"):
        adapter.set_default_ca_bundle(pem_bytes)


# Collect import-time scratch so the consumer's first allocation lands in a cleaner heap.
gc.collect()
