"""Default :mod:`chumicro_sockets` wiring for :class:`MQTTClient`.

Opt-in: the package's ``__init__.py`` does not import this submodule,
so users who pass their own ``socket`` or ``connector_factory`` never
pull :mod:`chumicro_sockets` into the deploy graph.
"""

from chumicro_config import MissingConfigKey


def chumicro_sockets_connector_factory(config, *, radio=None, ssl_context=None):
    """Build a ``() -> SocketConnector`` factory from *config*.

    Reads ``mqtt.broker.host`` / ``mqtt.broker.port``.  Both are
    required so the library never silently dials a third-party broker.
    Routes through :func:`chumicro_sockets.tls_client_connector` when
    *ssl_context* is supplied, otherwise :func:`tcp_client_connector`.
    Missing keys raise :class:`chumicro_config.MissingConfigKey`.

    The returned callable is what ``MQTTClient(connector_factory=...)``
    expects: each invocation hands back a fresh non-blocking connector
    in ``"awaiting_dns"``.  :class:`MQTTClient` drives it across ticks
    so the runner is not blocked for the DNS / TCP / TLS round-trip.
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
            from chumicro_sockets import tcp_client_connector  # noqa: PLC0415 - lazy

            return tcp_client_connector(host, port, radio=radio)

        return factory

    def factory():
        from chumicro_sockets import tls_client_connector  # noqa: PLC0415 - lazy

        return tls_client_connector(host, port, context=ssl_context, radio=radio)

    return factory
