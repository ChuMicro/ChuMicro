"""mqtt client: from_config construction."""

from chumicro_mqtt import MQTTClient
from chumicro_sockets.testing import FakeSocket
from chumicro_test_harness import skip
from chumicro_test_harness.assertions import raises


class TestFromConfig:
    """``MQTTClient.from_config`` reads the manifest's optional keys
    with sensible defaults; non-config args (socket, socket_factory,
    radio) come through kwargs."""

    @staticmethod
    def _injected_factory(sock: FakeSocket):
        """Return a socket_factory that hands back *sock*."""
        return lambda: sock

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
            config, socket_factory=self._injected_factory(sock),
        )
        assert client._client_id == "thing-007"  # noqa: SLF001
        assert client._keep_alive_seconds == 120  # noqa: SLF001
        assert client._username == "bob"  # noqa: SLF001
        assert client._password == "pw"  # noqa: SLF001

    def test_defaults_apply_when_keys_absent(self) -> None:
        """Empty config dict → every manifest key falls back to its default."""
        sock = FakeSocket()
        client = MQTTClient.from_config(
            {}, socket_factory=self._injected_factory(sock),
        )
        assert client._client_id == "chumicro-mqtt"  # noqa: SLF001
        assert client._keep_alive_seconds == 60  # noqa: SLF001
        assert client._username is None  # noqa: SLF001
        assert client._password is None  # noqa: SLF001

    def test_partial_config_mixes_overrides_with_defaults(self) -> None:
        """Caller-set keys win; absent keys take defaults."""
        sock = FakeSocket()
        client = MQTTClient.from_config(
            {"mqtt.client_id": "halfway"},
            socket_factory=self._injected_factory(sock),
        )
        assert client._client_id == "halfway"  # noqa: SLF001
        assert client._keep_alive_seconds == 60  # noqa: SLF001 — default
        assert client._username is None  # noqa: SLF001 — default

    def test_explicit_socket_bypasses_factory(self) -> None:
        """Passing a pre-built socket skips the auto-built factory entirely
        — caller owns the connection."""
        sock = FakeSocket()
        client = MQTTClient.from_config({}, socket=sock)
        assert client._socket is sock  # noqa: SLF001

    def test_runtime_config_wrapper_works_too(self) -> None:
        """Real ``RuntimeConfig`` instance — same flat-key reads as a
        plain dict.  Confirms compatibility with ``chumicro_config.config``
        on a real device."""
        from chumicro_config import RuntimeConfig  # noqa: PLC0415

        sock = FakeSocket()
        config = RuntimeConfig({
            "mqtt.client_id": "rc-test",
            "mqtt.keep_alive_seconds": 45,
        })
        client = MQTTClient.from_config(
            config, socket_factory=self._injected_factory(sock),
        )
        assert client._client_id == "rc-test"  # noqa: SLF001
        assert client._keep_alive_seconds == 45  # noqa: SLF001

    def test_default_factory_uses_config_broker_host_port(self) -> None:
        """When neither *socket* nor *socket_factory* is passed,
        ``from_config`` builds a factory that reads
        ``mqtt.broker.host`` / ``mqtt.broker.port`` from the config.
        Validates the factory closure without needing a real socket
        by monkey-patching ``chumicro_sockets.tcp_client_socket``,
        which the factory closure reaches at call time."""
        captured: dict = {}

        def fake_tcp_client_socket(host, port, *, radio=None):
            captured["host"] = host
            captured["port"] = port
            captured["radio"] = radio
            return FakeSocket()

        import chumicro_sockets  # noqa: PLC0415

        original = chumicro_sockets.tcp_client_socket
        chumicro_sockets.tcp_client_socket = fake_tcp_client_socket
        try:
            client = MQTTClient.from_config(
                {"mqtt.broker.host": "10.0.0.42", "mqtt.broker.port": 8883},
                radio="fake-radio",
            )
            # Construction is side-effect free — factory fires on connect().
            assert captured == {}
            client.connect()
        finally:
            chumicro_sockets.tcp_client_socket = original

        assert captured == {"host": "10.0.0.42", "port": 8883, "radio": "fake-radio"}

    def test_ssl_context_routes_through_tls_factory(self) -> None:
        """``ssl_context=`` supplied → auto-built factory uses
        :func:`chumicro_sockets.tls_client_socket` and threads the
        context + radio through.  Matches the TLS shape every other
        ``from_config`` in the workspace exposes (requests,
        websockets, http_server)."""
        captured: dict = {}

        def fake_tls_client_socket(host, port, *, context=None, radio=None):
            captured["host"] = host
            captured["port"] = port
            captured["context"] = context
            captured["radio"] = radio
            return FakeSocket()

        import chumicro_sockets  # noqa: PLC0415

        original = chumicro_sockets.tls_client_socket
        chumicro_sockets.tls_client_socket = fake_tls_client_socket
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
            chumicro_sockets.tls_client_socket = original

        assert captured == {
            "host": "broker.example",
            "port": 8883,
            "context": "fake-ctx",
            "radio": "fake-radio",
        }

    def test_ssl_context_ignored_when_socket_factory_passed(self) -> None:
        """``ssl_context=`` is documented as ignored when *socket* or
        *socket_factory* is supplied — caller-owned factories already
        encode their own TLS choice.  Confirms the dispatch doesn't
        accidentally consult ``ssl_context`` once a factory is in hand."""
        sock = FakeSocket()
        client = MQTTClient.from_config(
            {},
            socket_factory=self._injected_factory(sock),
            ssl_context="should-be-ignored",
        )
        # Construction is side-effect free; calling connect() wires the
        # socket via the injected factory.
        client.connect()
        assert client._socket is sock  # noqa: SLF001

    def test_default_factory_requires_broker_host(self) -> None:
        """No broker host in config → ``from_config`` refuses to
        construct.  The library does not silently dial a third-party
        broker on the user's behalf."""
        from chumicro_config import MissingConfigKey  # noqa: PLC0415

        with raises(MissingConfigKey):
            MQTTClient.from_config({})

    def test_default_factory_requires_broker_port(self) -> None:
        """Host present but port missing still raises — both keys are
        required by the auto-built socket factory."""
        from chumicro_config import MissingConfigKey  # noqa: PLC0415

        with raises(MissingConfigKey):
            MQTTClient.from_config({"mqtt.broker.host": "10.0.0.42"})

    def test_skipped_factory_module_raises_runtime_error(self) -> None:
        """When ``chumicro_mqtt.sockets_factory`` is excluded via
        ``__chumicro_skip_factories__``, the default branch of
        ``from_config`` raises ``RuntimeError`` naming the bypass
        kwarg instead of leaking ``ImportError``.

        Simulates the post-deploy state by stuffing ``None`` into
        ``sys.modules`` for the factory submodule — a ``None`` entry
        makes a subsequent ``import`` raise ``ImportError`` on
        CPython.  MicroPython / CircuitPython do not honor the
        ``None``-sentinel convention so the test only runs on
        CPython; the RuntimeError-translation behavior itself is
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
                assert "socket_factory=" in str(exception)
                assert "__chumicro_skip_factories__" in str(exception)
            else:
                raise AssertionError("expected RuntimeError")
        finally:
            if original is None:
                sys.modules.pop("chumicro_mqtt.sockets_factory", None)
            else:
                sys.modules["chumicro_mqtt.sockets_factory"] = original
