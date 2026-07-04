"""Default :mod:`chumicro_sockets` wiring for :class:`HttpClient`.

Opt-in submodule — the package's ``__init__.py`` does not import it,
so users who pass their own ``transport_factory`` never pull
:mod:`chumicro_sockets` into the deploy graph.
"""

import chumicro_sockets


def chumicro_sockets_connector_factory(*, radio=None, ssl_context=None):
    """Build a ``(host, port, use_tls) -> SocketConnector`` factory.

    Routes to :func:`chumicro_sockets.connector` — ``use_tls`` maps to
    its ``tls=`` flag, with the supplied *ssl_context* (or the runtime
    default when omitted).

    The returned callable is what
    ``HttpClient(transport_factory=...)`` expects: per-request hop the
    client invokes ``factory(host, port, use_tls)`` and drives the
    resulting non-blocking connector across ticks until ``ready``.
    """
    def factory(host, port, use_tls):
        return chumicro_sockets.connector(
            host, port,
            tls=use_tls,
            context=ssl_context if use_tls else None,
            radio=radio,
        )

    return factory
