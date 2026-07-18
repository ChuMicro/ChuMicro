"""Default :mod:`chumicro_sockets` wiring for :class:`MQTTClient`.

Opt-in: the package's ``__init__.py`` does not import this submodule,
so users who pass their own ``socket`` or ``transport_factory`` never
pull :mod:`chumicro_sockets` into the deploy graph.
"""

from chumicro_config import MissingConfigKey


def chumicro_sockets_connector_factory(config, *, radio=None, ssl_context=None):
    """Build a ``() -> SocketConnector`` factory from *config*.

    Reads the required ``mqtt.broker.host`` / ``mqtt.broker.port`` so the
    library never silently dials a third-party broker. Passing an
    *ssl_context* routes through :func:`chumicro_sockets.connector` with
    ``tls=True``.

    Returns:
        A zero-arg callable, the shape ``MQTTClient(transport_factory=...)``
        expects. Each call returns a fresh non-blocking connector that the
        client drives across ticks, so the runner never blocks on the
        DNS / TCP / TLS round-trip.

    Raises:
        MissingConfigKey: A required broker key is missing.
    """
    for required_key in ("mqtt.broker.host", "mqtt.broker.port"):
        if required_key not in config:
            raise MissingConfigKey(
                f"required config key {required_key!r} is missing",
            )
    host = config["mqtt.broker.host"]
    port = config["mqtt.broker.port"]

    def factory():
        from chumicro_sockets import connector  # noqa: PLC0415 - lazy

        return connector(
            host, port,
            tls=ssl_context is not None,
            context=ssl_context,
            radio=radio,
        )

    return factory
