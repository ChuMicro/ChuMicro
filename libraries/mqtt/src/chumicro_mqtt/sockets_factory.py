"""Default :mod:`chumicro_sockets` wiring for :class:`MQTTClient`."""

from chumicro_config import MissingConfigKey


def chumicro_sockets_connector_factory(config, *, radio=None, ssl_context=None):
    """Build a ``() -> SocketConnector`` factory from *config*.

    Returns:
        A zero-arg callable returning a fresh non-blocking connector.

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
