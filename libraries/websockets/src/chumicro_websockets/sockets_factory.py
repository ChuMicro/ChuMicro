"""Default :mod:`chumicro_sockets` wiring for the WebSocket client and server.

Opt-in submodule.  The package's ``__init__.py`` does not import it,
so users who pass their own ``connector_factory`` (client) or
``listener`` (server) never pull :mod:`chumicro_sockets` into the
deploy graph.
"""


def chumicro_sockets_listener(config, *, radio=None):
    """Build the default WebSocket-server listening socket from *config*.

    Reads ``websockets.server.host`` / ``websockets.server.port``
    (defaulting to ``0.0.0.0:8765``) and binds a
    :func:`chumicro_sockets.tcp_listening_socket`.

    Lives here, not in the eagerly-imported ``server`` module, so a
    client-only deploy that skips this factory submodule never drags
    :mod:`chumicro_sockets` onto the board.
    """
    from chumicro_sockets import tcp_listening_socket  # noqa: PLC0415 - lazy

    host = config.get("websockets.server.host", "0.0.0.0")
    port = config.get("websockets.server.port", 8765)
    return tcp_listening_socket(host, port, radio=radio)


def chumicro_sockets_connector_factory(*, radio=None, ssl_context=None):
    """Build a ``(host, port, use_tls) -> connector`` factory.

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
