"""Default :mod:`chumicro_sockets` wiring for :class:`WebSocketClient`.

Opt-in submodule.  The package's ``__init__.py`` does not import it,
so users who pass their own ``connector_factory`` never pull
:mod:`chumicro_sockets` into the deploy graph.
"""


def chumicro_sockets_connector_factory(*, radio=None, ssl_context=None):
    """Build a ``(host, port, use_tls) -> SocketConnector`` factory.

    Plain TCP routes to :func:`chumicro_sockets.tcp_client_connector`;
    TLS routes to :func:`chumicro_sockets.tls_client_connector` with
    the supplied *ssl_context*.  CA pinning via
    :func:`chumicro_sockets.ssl_context_with_ca` is required for
    ``wss://`` on constrained boards.

    The returned callable is what
    ``WebSocketClient(connector_factory=...)`` expects: each connect()
    invokes ``factory(host, port, use_tls)`` and drives the resulting
    non-blocking connector across ticks until ``ready`` before the
    HTTP upgrade exchange begins.
    """
    def factory(host, port, use_tls):
        from chumicro_sockets import (  # noqa: PLC0415 - lazy
            tcp_client_connector,
            tls_client_connector,
        )

        if use_tls:
            return tls_client_connector(host, port, context=ssl_context, radio=radio)
        return tcp_client_connector(host, port, radio=radio)

    return factory
