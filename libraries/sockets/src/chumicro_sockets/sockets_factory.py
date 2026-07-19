"""Generic transport factories for the chumicro networking libraries.

Builders take hosts, ports, and TLS material as parameters.  Protocol
config namespaces (``mqtt.broker.host`` and friends) belong to each
protocol library's ``from_config``, never here.

The module name ends in ``_factory`` so the deploy walker's
``__chumicro_skip_factories__`` family matching drops it from
bring-your-own-transport deploys, and with it the only reference that
would pull :mod:`chumicro_sockets` onto the board.
"""

import chumicro_sockets


def connector_factory(*, radio=None, ssl_context=None):
    """Build a ``(host, port, use_tls) -> SocketConnector`` factory."""
    def factory(host, port, use_tls):
        return chumicro_sockets.connector(
            host, port,
            tls=use_tls,
            context=ssl_context if use_tls else None,
            radio=radio,
        )

    return factory


def fixed_connector_factory(host, port, *, radio=None, ssl_context=None):
    """Build a ``() -> SocketConnector`` factory for one fixed endpoint."""
    def factory():
        return chumicro_sockets.connector(
            host, port,
            tls=ssl_context is not None,
            context=ssl_context,
            radio=radio,
        )

    return factory


def listener_factory(host, port, *, radio=None, ssl_context=None,
                     cert_path=None, key_path=None):
    """Build a ``() -> ListeningSocket`` factory, TLS when material is given.

    TLS engages when *ssl_context* or *cert_path* is set; an explicit
    *ssl_context* wins over paths.
    """
    use_tls = ssl_context is not None or cert_path is not None

    def factory():
        if not use_tls:
            return chumicro_sockets.listener(host, port, radio=radio)
        context = (
            ssl_context
            if ssl_context is not None
            else chumicro_sockets.ssl_context_with_cert_and_key_paths(
                cert_path=cert_path, key_path=key_path,
            )
        )
        return chumicro_sockets.listener(
            host, port, tls=True, context=context, radio=radio,
        )

    return factory


def udp_socket_factory(*, radio=None):
    """Build a ``() -> socket`` factory returning a fresh bound UDP socket."""
    def factory():
        return chumicro_sockets.udp_socket(radio=radio)

    return factory
