"""Default :mod:`chumicro_sockets` wiring for :class:`WebSocketClient`.

Opt-in submodule — the package's ``__init__.py`` does not import it,
so users who pass their own ``connection_factory`` never pull
:mod:`chumicro_sockets` into the deploy graph.
"""


def chumicro_sockets_factory(*, radio=None, ssl_context=None):
    """Build a ``(host, port, use_tls) -> TCPClientSocket`` factory.

    Plain TCP routes to :func:`chumicro_sockets.tcp_client_socket`;
    TLS routes to :func:`chumicro_sockets.tls_client_socket` with the
    supplied *ssl_context*.  CA pinning via
    :func:`chumicro_sockets.ssl_context_with_ca` is required for
    ``wss://`` on constrained boards.
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
