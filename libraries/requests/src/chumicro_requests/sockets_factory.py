"""Default :mod:`chumicro_sockets` wiring for :class:`HttpClient`.

Opt-in submodule — the package's ``__init__.py`` does not import it,
so users who pass their own ``connection_factory`` never pull
:mod:`chumicro_sockets` into the deploy graph.
"""

import chumicro_sockets


def chumicro_sockets_factory(*, radio=None, ssl_context=None):
    """Build a ``(host, port, use_tls) -> TCPClientSocket`` factory.

    Plain TCP routes to :func:`chumicro_sockets.tcp_client_socket`;
    TLS routes to :func:`chumicro_sockets.tls_client_socket` with the
    supplied *ssl_context* (or the runtime default when omitted).
    """
    def factory(host, port, use_tls):
        if use_tls:
            return chumicro_sockets.tls_client_socket(
                host, port, context=ssl_context, radio=radio,
            )
        return chumicro_sockets.tcp_client_socket(host, port, radio=radio)

    return factory
