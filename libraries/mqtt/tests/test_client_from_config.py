"""mqtt client: from_config construction."""

from chumicro_mqtt import MQTTClient, default_client_id
from chumicro_sockets.testing import FakeSocket, FakeSocketConnector


class TestFromConfig:
    """``MQTTClient.from_config`` reads the manifest's optional keys
    with sensible defaults.  Non-config args (socket, transport_factory,
    radio) come through kwargs."""

    @staticmethod
    def _injected_factory(sock: FakeSocket):
        """Return a transport_factory that yields *sock* on the second tick."""
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
            config, transport_factory=self._injected_factory(sock),
        )
        assert client._client_id == "thing-007"  # noqa: SLF001
        assert client._keep_alive_seconds == 120  # noqa: SLF001
        assert client._username == "bob"  # noqa: SLF001
        assert client._password == "pw"  # noqa: SLF001

    def test_defaults_apply_when_keys_absent(self) -> None:
        """An empty config dict makes every manifest key fall back to its default."""
        sock = FakeSocket()
        client = MQTTClient.from_config(
            {}, transport_factory=self._injected_factory(sock),
        )
        # No mqtt.client_id in config → a stable per-device id, not the old
        # fixed "chumicro-mqtt" that collided across devices on one broker.
        assert client._client_id == default_client_id()  # noqa: SLF001
        assert client._client_id.startswith("chumicro-")  # noqa: SLF001
        assert client._keep_alive_seconds == 60  # noqa: SLF001
        assert client._username is None  # noqa: SLF001
        assert client._password is None  # noqa: SLF001

    def test_partial_config_mixes_overrides_with_defaults(self) -> None:
        """Caller-set keys win.  Absent keys take defaults."""
        sock = FakeSocket()
        client = MQTTClient.from_config(
            {"mqtt.client_id": "halfway"},
            transport_factory=self._injected_factory(sock),
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
            config, transport_factory=self._injected_factory(sock),
        )
        assert client._client_id == "rc-test"  # noqa: SLF001
        assert client._keep_alive_seconds == 45  # noqa: SLF001


class TestDefaultClientId:
    """default_client_id derives a stable per-device MQTT id."""

    def test_starts_with_prefix_and_is_stable(self) -> None:
        first = default_client_id()
        assert first.startswith("chumicro-")
        # Stable across calls (same host UID), so a persistent session resumes.
        assert first == default_client_id()

    def test_custom_prefix(self) -> None:
        assert default_client_id(prefix="dev").startswith("dev-")
