"""Default :mod:`chumicro_sockets` wiring for :class:`MQTTClient`.

Opt-in: the package's ``__init__.py`` does not import this submodule,
so users who pass their own ``socket`` or ``transport_factory`` never
pull :mod:`chumicro_sockets` into the deploy graph.
"""

from chumicro_config import MissingConfigKey


def chumicro_sockets_connector_factory(config, *, radio=None, ssl_context=None):
    """Build a ``() -> SocketConnector`` factory from *config*.

    Reads ``mqtt.broker.host`` / ``mqtt.broker.port``.  Both are
    required so the library never silently dials a third-party broker.
    Routes through :func:`chumicro_sockets.connector` with ``tls=True``
    when *ssl_context* is supplied.  Missing keys raise
    :class:`chumicro_config.MissingConfigKey`.

    The returned callable is what ``MQTTClient(transport_factory=...)``
    expects: each invocation hands back a fresh non-blocking connector
    in ``"awaiting_dns"``.  :class:`MQTTClient` drives it across ticks
    so the runner is not blocked for the DNS / TCP / TLS round-trip.
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
