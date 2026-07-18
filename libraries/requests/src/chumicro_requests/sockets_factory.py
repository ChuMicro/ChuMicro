"""Default :mod:`chumicro_sockets` wiring for :class:`HttpClient`.

Opt-in submodule: the package's ``__init__.py`` does not import it, so
users who pass their own ``transport_factory`` never pull
:mod:`chumicro_sockets` into the deploy graph.
"""

import chumicro_sockets


def chumicro_sockets_connector_factory(*, radio=None, ssl_context=None):
    """Build a ``(host, port, use_tls) -> SocketConnector`` factory.

    The returned callable is what ``HttpClient(transport_factory=...)``
    expects: per request hop the client calls ``factory(host, port,
    use_tls)`` and drives the non-blocking connector across ticks until
    it is ``ready``. ``use_tls`` selects TLS via the connector's ``tls=``
    flag, using *ssl_context* (or the runtime default when omitted).
    """
    def factory(host, port, use_tls):
        return chumicro_sockets.connector(
            host, port,
            tls=use_tls,
            context=ssl_context if use_tls else None,
            radio=radio,
        )

    return factory
