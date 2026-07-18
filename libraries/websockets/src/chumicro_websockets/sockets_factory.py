"""Default :mod:`chumicro_sockets` wiring for the WebSocket client and server.

Opt-in submodule.  The package's ``__init__.py`` does not import it,
so users who pass their own ``transport_factory`` (client) or
``listener`` (server) never pull :mod:`chumicro_sockets` into the
deploy graph.
"""


def chumicro_sockets_listener(config, *, radio=None):
    """Build the default WebSocket-server listening socket from *config*.

    Reads ``websockets.server.host`` / ``websockets.server.port``
    (defaulting to ``0.0.0.0:8765``) and binds a
    :func:`chumicro_sockets.listener`.
    """
    from chumicro_sockets import listener  # noqa: PLC0415 - lazy

    host = config.get("websockets.server.host", "0.0.0.0")
    port = config.get("websockets.server.port", 8765)
    return listener(host, port, radio=radio)


def chumicro_sockets_connector_factory(*, radio=None, ssl_context=None):
    """Build a ``(host, port, use_tls) -> connector`` factory.

    Routes to :func:`chumicro_sockets.connector`, mapping ``use_tls`` to
    its ``tls=`` flag with the supplied *ssl_context*. CA pinning via
    :func:`chumicro_sockets.ssl_context_with_ca` is required for ``wss://``
    on constrained boards.
    """
    def factory(host, port, use_tls):
        from chumicro_sockets import connector  # noqa: PLC0415 - lazy

        return connector(
            host, port,
            tls=use_tls,
            context=ssl_context if use_tls else None,
            radio=radio,
        )

    return factory
