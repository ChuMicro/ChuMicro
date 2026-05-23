"""mqtt client: from_config construction."""

from chumicro_mqtt import MQTTClient
from chumicro_sockets.testing import FakeSocket, FakeSocketConnector
from chumicro_test_harness import skip
from chumicro_test_harness.assertions import raises


class TestFromConfig:
    """``MQTTClient.from_config`` reads the manifest's optional keys
    with sensible defaults.  Non-config args (socket, connector_factory,
    radio) come through kwargs."""

    @staticmethod
    def _injected_factory(sock: FakeSocket):
        """Return a connector_factory that yields *sock* on the second tick."""
        return lambda: FakeSocketConnector(
            actions=["dns_ok", "tcp_ok"], socket=sock,
        )

    def test_reads_all_keys_from_config(self) -> None:
        """A complete config dict populates every documented manifest key."""
        sock = FakeSocket()
        config = {
            "mqtt.broker.host": "10.0.0.5",  # consumed by default factory only
            "mqtt.broker.port": 8883,         # consumed by default factory only
            "mqtt.client_id": "thing-007",
            "mqtt.keep_alive_seconds": 120,
            "mqtt.username": "bob",
            "mqtt.password": "pw",
        }
        client = MQTTClient.from_config(
            config, connector_factory=self._injected_factory(sock),
        )
        assert client._client_id == "thing-007"  # noqa: SLF001
        assert client._keep_alive_seconds == 120  # noqa: SLF001
        assert client._username == "bob"  # noqa: SLF001
        assert client._password == "pw"  # noqa: SLF001

    def test_defaults_apply_when_keys_absent(self) -> None:
        """An empty config dict makes every manifest key fall back to its default."""
        sock = FakeSocket()
        client = MQTTClient.from_config(
            {}, connector_factory=self._injected_factory(sock),
        )
        assert client._client_id == "chumicro-mqtt"  # noqa: SLF001
        assert client._keep_alive_seconds == 60  # noqa: SLF001
        assert client._username is None  # noqa: SLF001
        assert client._password is None  # noqa: SLF001

    def test_partial_config_mixes_overrides_with_defaults(self) -> None:
        """Caller-set keys win.  Absent keys take defaults."""
        sock = FakeSocket()
        client = MQTTClient.from_config(
            {"mqtt.client_id": "halfway"},
            connector_factory=self._injected_factory(sock),
        )
        assert client._client_id == "halfway"  # noqa: SLF001
        assert client._keep_alive_seconds == 60  # noqa: SLF001 - default
        assert client._username is None  # noqa: SLF001 - default

    def test_explicit_socket_bypasses_factory(self) -> None:
        """Passing a pre-built socket skips the auto-built factory entirely.
        Caller owns the connection."""
        sock = FakeSocket()
        client = MQTTClient.from_config({}, socket=sock)
        assert client._socket is sock  # noqa: SLF001

    def test_runtime_config_wrapper_works_too(self) -> None:
        """Real ``RuntimeConfig`` instance.  Same flat-key reads as a
        plain dict.  Confirms compatibility with ``chumicro_config.config``
        on a real device."""
        from chumicro_config import RuntimeConfig  # noqa: PLC0415

        sock = FakeSocket()
        config = RuntimeConfig({
            "mqtt.client_id": "rc-test",
            "mqtt.keep_alive_seconds": 45,
        })
        client = MQTTClient.from_config(
            config, connector_factory=self._injected_factory(sock),
        )
        assert client._client_id == "rc-test"  # noqa: SLF001
        assert client._keep_alive_seconds == 45  # noqa: SLF001

    def test_default_factory_uses_config_broker_host_port(self) -> None:
        """When neither *socket* nor *connector_factory* is passed,
        ``from_config`` builds a factory that reads
        ``mqtt.broker.host`` / ``mqtt.broker.port`` from the config.
        Validates the factory closure without needing a real socket
        by monkey-patching ``chumicro_sockets.tcp_client_connector``,
        which the factory closure reaches at call time."""
        captured: dict = {}

        def fake_tcp_client_connector(host, port, *, radio=None):
            captured["host"] = host
            captured["port"] = port
            captured["radio"] = radio
            return FakeSocketConnector(
                actions=["dns_ok", "tcp_ok"], socket=FakeSocket(),
            )

        import chumicro_sockets  # noqa: PLC0415

        original = chumicro_sockets.tcp_client_connector
        chumicro_sockets.tcp_client_connector = fake_tcp_client_connector
        try:
            client = MQTTClient.from_config(
                {"mqtt.broker.host": "10.0.0.42", "mqtt.broker.port": 8883},
                radio="fake-radio",
            )
            # Construction is side-effect free.  Factory fires on connect().
            assert captured == {}
            client.connect()
        finally:
            chumicro_sockets.tcp_client_connector = original

        assert captured == {"host": "10.0.0.42", "port": 8883, "radio": "fake-radio"}

    def test_ssl_context_routes_through_tls_factory(self) -> None:
        """When ``ssl_context=`` is supplied, the auto-built factory uses
        :func:`chumicro_sockets.tls_client_connector` and threads the
        context and radio through."""
        captured: dict = {}

        def fake_tls_client_connector(host, port, *, context=None, radio=None):
            captured["host"] = host
            captured["port"] = port
            captured["context"] = context
            captured["radio"] = radio
            return FakeSocketConnector(
                actions=["dns_ok", "tcp_ok"], socket=FakeSocket(),
            )

        import chumicro_sockets  # noqa: PLC0415

        original = chumicro_sockets.tls_client_connector
        chumicro_sockets.tls_client_connector = fake_tls_client_connector
        try:
            client = MQTTClient.from_config(
                {"mqtt.broker.host": "broker.example", "mqtt.broker.port": 8883},
                radio="fake-radio",
                ssl_context="fake-ctx",
            )
            # Factory is built but not invoked until connect().
            assert captured == {}
            client.connect()
        finally:
            chumicro_sockets.tls_client_connector = original

        assert captured == {
            "host": "broker.example",
            "port": 8883,
            "context": "fake-ctx",
            "radio": "fake-radio",
        }

    def test_ssl_context_ignored_when_connector_factory_passed(self) -> None:
        """``ssl_context=`` is documented as ignored when *socket* or
        *connector_factory* is supplied.  Caller-owned factories already
        encode their own TLS choice.  Confirms the dispatch doesn't
        accidentally consult ``ssl_context`` once a factory is in hand."""
        sock = FakeSocket()
        client = MQTTClient.from_config(
            {},
            connector_factory=self._injected_factory(sock),
            ssl_context="should-be-ignored",
        )
        # Construction is side-effect free.  Calling connect() arms the
        # connector via the injected factory; one tick promotes the socket.
        client.connect()
        # Drive the connector one tick to advance past AWAITING_TRANSPORT.
        client.handle(0)
        client.handle(0)
        assert client._socket is sock  # noqa: SLF001

    def test_default_factory_requires_broker_host(self) -> None:
        """When no broker host is configured, ``from_config`` refuses
        to construct.  The library does not silently dial a third-party
        broker on the user's behalf."""
        from chumicro_config import MissingConfigKey  # noqa: PLC0415

        with raises(MissingConfigKey):
            MQTTClient.from_config({})

    def test_default_factory_requires_broker_port(self) -> None:
        """Host present but port missing still raises.  Both keys are
        required by the auto-built connector factory."""
        from chumicro_config import MissingConfigKey  # noqa: PLC0415

        with raises(MissingConfigKey):
            MQTTClient.from_config({"mqtt.broker.host": "10.0.0.42"})

    def test_skipped_factory_module_raises_runtime_error(self) -> None:
        """When ``chumicro_mqtt.sockets_factory`` is excluded via
        ``__chumicro_skip_factories__``, the default branch of
        ``from_config`` raises ``RuntimeError`` naming the bypass
        kwarg instead of leaking ``ImportError``.

        Simulates the post-deploy state by stuffing ``None`` into
        ``sys.modules`` for the factory submodule.  A ``None`` entry
        makes a subsequent ``import`` raise ``ImportError`` on
        CPython.  MicroPython / CircuitPython do not honor the
        ``None``-sentinel convention so the test only runs on
        CPython.  The RuntimeError-translation behavior itself is
        runtime-agnostic (a real on-device skip-factories deploy
        triggers the same code path).
        """
        import sys  # noqa: PLC0415

        if sys.implementation.name != "cpython":
            skip("sys.modules None-sentinel is CPython-specific")

        original = sys.modules.get("chumicro_mqtt.sockets_factory")
        sys.modules["chumicro_mqtt.sockets_factory"] = None
        try:
            try:
                MQTTClient.from_config(
                    {"mqtt.broker.host": "h", "mqtt.broker.port": 1883},
                )
            except RuntimeError as exception:
                assert "connector_factory=" in str(exception)
                assert "__chumicro_skip_factories__" in str(exception)
            else:
                raise AssertionError("expected RuntimeError")
        finally:
            if original is None:
                sys.modules.pop("chumicro_mqtt.sockets_factory", None)
            else:
                sys.modules["chumicro_mqtt.sockets_factory"] = original
