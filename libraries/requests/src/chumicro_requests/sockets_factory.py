"""Default :mod:`chumicro_sockets` wiring for :class:`HttpClient`.

Opt-in submodule — the package's ``__init__.py`` does not import it,
so users who pass their own ``connector_factory`` never pull
:mod:`chumicro_sockets` into the deploy graph.
"""

import chumicro_sockets


def chumicro_sockets_connector_factory(*, radio=None, ssl_context=None):
    """Build a ``(host, port, use_tls) -> SocketConnector`` factory.

    Plain TCP routes to :func:`chumicro_sockets.tcp_client_connector`;
    TLS routes to :func:`chumicro_sockets.tls_client_connector` with
    the supplied *ssl_context* (or the runtime default when omitted).

    The returned callable is what
    ``HttpClient(connector_factory=...)`` expects: per-request hop the
    client invokes ``factory(host, port, use_tls)`` and drives the
    resulting non-blocking connector across ticks until ``ready``.
    """
    def factory(host, port, use_tls):
        if use_tls:
            return chumicro_sockets.tls_client_connector(
                host, port, context=ssl_context, radio=radio,
            )
        return chumicro_sockets.tcp_client_connector(host, port, radio=radio)

    return factory
