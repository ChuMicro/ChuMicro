"""Default :mod:`chumicro_sockets` wiring for :class:`chumicro_websockets.WebSocketClient`.

Per [Decision 0042 §Sub-rule](../../plans/decisions/0042-library-dependency-policy.md)
this helper lives in its own submodule — the package's ``__init__.py``
does **not** import it.  Users who want the default wiring opt in
explicitly::

    from chumicro_websockets import WebSocketClient
    from chumicro_websockets.sockets_factory import chumicro_sockets_factory
    from chumicro_wifi import wifi

    client = WebSocketClient(
        connection_factory=chumicro_sockets_factory(radio=wifi.adapter.radio),
    )
    client.connect("wss://api.example.com/stream")

Users injecting a custom transport simply skip the import — the
deploy-time AST walker (Decision 0029) won't follow what isn't
referenced, so :mod:`chumicro_sockets` doesn't ship to the device
even though it sits in ``[project].dependencies``.

This is the first chumicro library to ship the helper in its own
submodule from day 1; :mod:`chumicro_requests` retrofits the same
shape in a follow-up audit per the
[Decision 0042](../../plans/decisions/0042-library-dependency-policy.md)
audit checklist.
"""


def chumicro_sockets_factory(*, radio=None, ssl_context=None):
    """Return a ``connection_factory`` wired to :mod:`chumicro_sockets`.

    The returned callable matches the
    ``connection_factory(host, port, use_tls) -> TCPClientSocket``
    signature :class:`chumicro_websockets.WebSocketClient` expects.
    Plain TCP routes to :func:`chumicro_sockets.tcp_client_socket`;
    TLS routes to :func:`chumicro_sockets.tls_client_socket` with
    the supplied *ssl_context* (or the runtime default when omitted).

    Args:
        radio: Required on CircuitPython (typically ``wifi.radio``
            from :mod:`chumicro_wifi`); ignored on MicroPython and
            CPython.
        ssl_context: Pre-built :class:`ssl.SSLContext` to use for
            ``wss://`` connections.  Build via
            :func:`chumicro_sockets.ssl_context_with_ca` for the
            CA-pinned shape :class:`chumicro_websockets.WebSocketClient`
            recommends (see Decision 0040 §"Live-board limitations"
            for why CA pinning is required on every supported runtime).

    Returns:
        A ``callable(host, port, use_tls)`` ready to pass into
        :class:`chumicro_websockets.WebSocketClient`'s
        ``connection_factory=`` parameter.

    Lazy-imports :mod:`chumicro_sockets` so this submodule can be
    unit-tested without the transport on PYTHONPATH and so the
    deploy walker doesn't follow the transport import unless the
    user actually references this submodule.
    """
    def factory(host, port, use_tls):
        from chumicro_sockets import (  # noqa: PLC0415 - lazy
            tcp_client_socket,
            tls_client_socket,
        )

        if use_tls:
            return tls_client_socket(host, port, context=ssl_context, radio=radio)
        return tcp_client_socket(host, port, radio=radio)

    return factory
