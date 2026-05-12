"""Default :mod:`chumicro_sockets` wiring for :class:`chumicro_mqtt.MQTTClient`.

Helpers that import a chumicro core-infrastructure library live in
their own submodule — the package's ``__init__.py`` does **not**
import this one.  Users who want the default wiring opt in
explicitly::

    from chumicro_mqtt import MQTTClient
    from chumicro_mqtt.sockets_factory import chumicro_sockets_factory

    factory = chumicro_sockets_factory(
        {"mqtt.broker.host": "broker.example.com", "mqtt.broker.port": 1883},
    )
    client = MQTTClient(socket_factory=factory, client_id="my-thing")

:meth:`MQTTClient.from_config` reaches for this helper internally
when the caller doesn't supply *socket* or *socket_factory*, so the
config-driven entry point keeps working without changes — users
who pass their own factory simply never reference this submodule
and :mod:`chumicro_sockets` stays out of their deploy.
"""

from chumicro_config import MissingConfigKey


def chumicro_sockets_factory(config, *, radio=None, ssl_context=None):
    """Return a ``() -> TCPClientSocket`` factory wired to :mod:`chumicro_sockets`.

    Reads ``mqtt.broker.host`` / ``mqtt.broker.port`` from *config*
    and bakes them into the returned 0-arg callable.  Both keys are
    required — the library refuses to silently dial a third-party
    broker on the user's behalf.

    When *ssl_context* is supplied the factory routes through
    :func:`chumicro_sockets.tls_client_socket`; otherwise it uses
    :func:`chumicro_sockets.tcp_client_socket`.

    Args:
        config: A :class:`chumicro_config.RuntimeConfig` (typically
            ``chumicro_config.config``) or plain flat dict.  Keys
            read are flat dotted strings (``"mqtt.broker.host"``).
        radio: CP-only radio object.  Defaults to ``wifi.radio`` on CP
            (auto-detected); ignored on MP and CPython.  Pass explicitly
            for multi-radio prototypes or boards without a ``wifi`` module.
        ssl_context: Pre-built :class:`ssl.SSLContext` for
            ``mqtts://`` brokers (typically port 8883).  Build via
            :func:`chumicro_sockets.ssl_context_with_ca` for CA pinning;
            ``None`` keeps the plain-TCP path.

    Returns:
        A ``callable() -> TCPClientSocket`` ready to pass into
        :class:`chumicro_mqtt.MQTTClient`'s ``socket_factory=`` parameter.

    Raises:
        chumicro_config.MissingConfigKey: ``mqtt.broker.host`` or
            ``mqtt.broker.port`` is absent from *config*.

    Lazy-imports :mod:`chumicro_sockets` inside the returned closure
    so this submodule can be unit-tested without the transport on
    PYTHONPATH and so the deploy walker doesn't follow the transport
    import unless the user actually references this submodule.
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
