"""Default :mod:`chumicro_sockets` wiring for :class:`chumicro_websockets.WebSocketClient`.

Helpers that import a chumicro core-infrastructure library live in
their own submodule — the package's ``__init__.py`` does **not**
import this one.  Users who want the default wiring opt in
explicitly::

    from chumicro_websockets import WebSocketClient
    from chumicro_websockets.sockets_factory import chumicro_sockets_factory

    client = WebSocketClient(connection_factory=chumicro_sockets_factory())
    client.connect("wss://api.example.com/stream")

Users injecting a custom transport simply skip the import — the
deploy-time AST walker won't follow what isn't referenced, so
:mod:`chumicro_sockets` doesn't ship to the device even though it
sits in ``[project].dependencies``.
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
        radio: CP-only radio object.  Defaults to ``wifi.radio`` on CP
            (auto-detected); ignored on MP and CPython.  Pass explicitly
            for multi-radio prototypes or boards without a ``wifi`` module.
        ssl_context: Pre-built :class:`ssl.SSLContext` to use for
            ``wss://`` connections.  Build via
            :func:`chumicro_sockets.ssl_context_with_ca` for the
            CA-pinned shape :class:`chumicro_websockets.WebSocketClient`
            recommends (CA pinning is required on every supported
            runtime since live-board TLS without it can't validate
            the chain end-to-end on constrained boards).

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
