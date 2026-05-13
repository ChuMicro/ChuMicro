"""Default :mod:`chumicro_sockets` wiring for :class:`MQTTClient`.

Opt-in submodule — the package's ``__init__.py`` does not import it,
so users who pass their own ``socket`` or ``socket_factory`` never
pull :mod:`chumicro_sockets` into the deploy graph.
"""

from chumicro_config import MissingConfigKey


def chumicro_sockets_factory(config, *, radio=None, ssl_context=None):
    """Build a ``() -> TCPClientSocket`` factory from *config*.

    Reads ``mqtt.broker.host`` / ``mqtt.broker.port`` — both required;
    the library refuses to silently dial a third-party broker.  Routes
    through :func:`chumicro_sockets.tls_client_socket` when
    *ssl_context* is supplied, otherwise plain TCP.  Missing keys raise
    :class:`chumicro_config.MissingConfigKey`.
    """
    if "mqtt.broker.host" not in config:
        raise MissingConfigKey(
            "required config key 'mqtt.broker.host' is missing",
        )
    if "mqtt.broker.port" not in config:
        raise MissingConfigKey(
            "required config key 'mqtt.broker.port' is missing",
        )
    host = config["mqtt.broker.host"]
    port = config["mqtt.broker.port"]

    if ssl_context is None:
        def factory():
            from chumicro_sockets import tcp_client_socket  # noqa: PLC0415 - lazy

            return tcp_client_socket(host, port, radio=radio)

        return factory

    def factory():
        from chumicro_sockets import tls_client_socket  # noqa: PLC0415 - lazy

        return tls_client_socket(host, port, context=ssl_context, radio=radio)

    return factory
