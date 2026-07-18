"""Default :mod:`chumicro_sockets` wiring for :class:`HttpClient`."""

import chumicro_sockets


def chumicro_sockets_connector_factory(*, radio=None, ssl_context=None):
    """Build a ``(host, port, use_tls) -> SocketConnector`` factory."""
    def factory(host, port, use_tls):
        return chumicro_sockets.connector(
            host, port,
            tls=use_tls,
            context=ssl_context if use_tls else None,
            radio=radio,
        )

    return factory
