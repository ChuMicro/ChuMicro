"""mqtt client: from_config's auto-built transport factory.

Split from ``test_client_from_config.py`` so each file fits the
unix-lane heap budget (suite-slimming convention).
"""

from chumicro_mqtt import MQTTClient
from chumicro_sockets.testing import FakeSocket, FakeSocketConnector
from chumicro_test_harness import skip
from chumicro_test_harness.assertions import raises
from chumicro_timing.testing import FakeTicks


class TestFromConfigFactory:
    """The default-factory branch of ``from_config``: broker host/port
    reads, TLS routing via ``ssl_context=``, and the skip-factories
    RuntimeError translation."""

    @staticmethod
    def _injected_factory(sock: FakeSocket):
        """Return a transport_factory that yields *sock* on the second tick."""
        return lambda: FakeSocketConnector(
            actions=["dns_ok", "tcp_ok"], socket=sock,
        )

    def test_default_factory_uses_config_broker_host_port(self) -> None:
        """When neither *socket* nor *transport_factory* is passed,
        ``from_config`` builds a factory that reads
        ``mqtt.broker.host`` / ``mqtt.broker.port`` from the config.
        Validates the factory closure without needing a real socket
        by monkey-patching ``chumicro_sockets.connector``,
        which the factory closure reaches at call time."""
        captured: dict = {}

        def fake_connector(host, port, *, tls=False, context=None, radio=None):
            captured["host"] = host
            captured["port"] = port
            captured["tls"] = tls
            captured["context"] = context
            captured["radio"] = radio
            return FakeSocketConnector(
                actions=["dns_ok", "tcp_ok"], socket=FakeSocket(),
            )

        import chumicro_sockets  # noqa: PLC0415

        original = chumicro_sockets.connector
        chumicro_sockets.connector = fake_connector
        try:
            client = MQTTClient.from_config(
                {"mqtt.broker.host": "10.0.0.42", "mqtt.broker.port": 8883},
                radio="fake-radio",
            )
            # Construction is side-effect free.  Factory fires on connect().
            assert captured == {}
            client.connect()
        finally:
            chumicro_sockets.connector = original

        assert captured == {
            "host": "10.0.0.42",
            "port": 8883,
            "tls": False,
            "context": None,
            "radio": "fake-radio",
        }

    def test_ssl_context_routes_through_tls_factory(self) -> None:
        """When ``ssl_context=`` is supplied, the auto-built factory calls
        :func:`chumicro_sockets.connector` with ``tls=True`` and threads
        the context and radio through."""
        captured: dict = {}

        def fake_connector(host, port, *, tls=False, context=None, radio=None):
            captured["host"] = host
            captured["port"] = port
            captured["tls"] = tls
            captured["context"] = context
            captured["radio"] = radio
            return FakeSocketConnector(
                actions=["dns_ok", "tcp_ok"], socket=FakeSocket(),
            )

        import chumicro_sockets  # noqa: PLC0415

        original = chumicro_sockets.connector
        chumicro_sockets.connector = fake_connector
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
            chumicro_sockets.connector = original

        assert captured == {
            "host": "broker.example",
            "port": 8883,
            "tls": True,
            "context": "fake-ctx",
            "radio": "fake-radio",
        }

    def test_ssl_context_ignored_when_transport_factory_passed(self) -> None:
        """``ssl_context=`` is documented as ignored when *socket* or
        *transport_factory* is supplied.  Caller-owned factories already
        encode their own TLS choice.  Confirms the dispatch doesn't
        accidentally consult ``ssl_context`` once a factory is in hand."""
        sock = FakeSocket()
        # Inject the fake clock through from_config's ticks= seam so the
        # connect-attempt deadline armed inside connect() and the fake
        # nows below share one clock (see patterns.md "Fake-now tests").
        client = MQTTClient.from_config(
            {},
            transport_factory=self._injected_factory(sock),
            ssl_context="should-be-ignored",
            ticks=FakeTicks(),
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
        """When ``chumicro_sockets.sockets_factory`` is excluded via
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

        original = sys.modules.get("chumicro_sockets.sockets_factory")
        sys.modules["chumicro_sockets.sockets_factory"] = None
        try:
            try:
                MQTTClient.from_config(
                    {"mqtt.broker.host": "h", "mqtt.broker.port": 1883},
                )
            except RuntimeError as exception:
                assert "transport_factory=" in str(exception)
                assert "__chumicro_skip_factories__" in str(exception)
            else:
                raise AssertionError("expected RuntimeError")
        finally:
            if original is None:
                sys.modules.pop("chumicro_sockets.sockets_factory", None)
            else:
                sys.modules["chumicro_sockets.sockets_factory"] = original
