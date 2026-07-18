"""Default :mod:`chumicro_sockets` wiring for the WebSocket client and server."""


def chumicro_sockets_listener(config, *, radio=None):
    """Build the default WebSocket-server listening socket from *config*."""
    from chumicro_sockets import listener  # noqa: PLC0415 - lazy

    host = config.get("websockets.server.host", "0.0.0.0")
    port = config.get("websockets.server.port", 8765)
    return listener(host, port, radio=radio)


def chumicro_sockets_connector_factory(*, radio=None, ssl_context=None):
    """Build a ``(host, port, use_tls) -> connector`` factory."""
    def factory(host, port, use_tls):
        from chumicro_sockets import connector  # noqa: PLC0415 - lazy

        return connector(
            host, port,
            tls=use_tls,
            context=ssl_context if use_tls else None,
            radio=radio,
        )

    return factory
