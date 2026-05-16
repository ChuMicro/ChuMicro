"""Live integration test against a real Mosquitto broker.

Spawns a Mosquitto process on a loopback port at module-load time
(skips the whole module when ``mosquitto`` isn't on PATH), connects
the chumicro-mqtt client over a real TCP socket, and runs end-to-end
publish/subscribe scenarios.

Catches regressions the FakeSocket suite can't see:

* Real broker timing — does the tick-based handle() loop converge
  fast enough that PUBACKs arrive within the 5 s ack timeout?
* Real wire format — every packet we send must be acceptable to a
  real MQTT 3.1.1 broker, not just our own decoder.
* Concurrent subscribers — the same client both publishes AND
  receives messages from itself, exercising the loop in both
  directions in one process.

Tests skip cleanly when ``mosquitto`` is unavailable (typical CI).

Why ``_pytest`` (CPython-only)
==============================

Spawning the Mosquitto subprocess requires :mod:`subprocess` (not on
MicroPython / CircuitPython) and :mod:`shutil.which` (same).  The
*test logic itself* — driving the chumicro-mqtt client against a
real broker — could in principle run on the unix-port if a host-side
wrapper spun up the broker first and handed the port number to the
unix-port test.  Worth doing if cross-runtime broker coverage
becomes valuable; today FakeSocket coverage + the on-device
functional tests (real broker over real wifi) are sufficient.
"""

#: CPython-only lane (pytest fixtures / host stdlib); not cross-runtime.
__chumicro_runtimes__ = ("cpython",)

import shutil
import socket
import subprocess
import time
from typing import TYPE_CHECKING

import pytest
from chumicro_mqtt import MQTTClient, ProtocolState
from chumicro_sockets import tcp_client_socket
from chumicro_timing import ticks_ms

if TYPE_CHECKING:  # pragma: no cover — type-only
    pass


# ---------------------------------------------------------------------------
# Mosquitto broker fixture (module-scoped)
# ---------------------------------------------------------------------------


def _find_free_port() -> int:
    """Bind a temporary socket and return the OS-allocated port."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def _wait_until_listening(port: int, *, deadline_seconds: float = 5.0) -> bool:
    """Poll ``127.0.0.1:port`` until something accepts a TCP connect."""
    deadline = time.monotonic() + deadline_seconds
    while time.monotonic() < deadline:
        try:
            probe = socket.create_connection(("127.0.0.1", port), timeout=0.5)
        except OSError:
            time.sleep(0.05)
            continue
        probe.close()
        return True
    return False


@pytest.fixture(scope="module")
def mosquitto_broker(tmp_path_factory: pytest.TempPathFactory):
    """Spawn a Mosquitto broker on a free loopback port.

    Skips the whole module when Mosquitto isn't on PATH.  Yields the
    port; tears down by signaling SIGTERM and reaping.
    """
    if shutil.which("mosquitto") is None:
        pytest.skip("mosquitto not on PATH — skipping live broker tests")

    port = _find_free_port()
    workdir = tmp_path_factory.mktemp("mosquitto")
    config_path = workdir / "broker.conf"
    config_path.write_text(
        f"listener {port} 127.0.0.1\n"
        "allow_anonymous true\n"
        "persistence false\n"
        f"log_dest file {workdir}/broker.log\n",
    )
    # Mosquitto 2.0 on macOS fails with "Out of memory" when it
    # tries to setrlimit(RLIMIT_NOFILE) above the soft limit; on
    # Apple Silicon this happens at default.  Drop the soft limit
    # in the child via preexec_fn before exec().
    def _reduce_fd_limit() -> None:  # pragma: no cover — runs in spawned child
        import resource  # noqa: PLC0415

        resource.setrlimit(resource.RLIMIT_NOFILE, (256, 256))

    process = subprocess.Popen(
        ["mosquitto", "-c", str(config_path)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        preexec_fn=_reduce_fd_limit,  # noqa: PLW1509 — needed for macOS rlimit quirk
    )
    if not _wait_until_listening(port):
        process.terminate()
        process.wait(timeout=2)
        log_path = workdir / "broker.log"
        log_text = log_path.read_text() if log_path.exists() else "(no log)"
        pytest.skip(f"mosquitto failed to start on port {port}; log:\n{log_text}")
    try:
        yield port
    finally:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _new_client(broker_port: int, client_id: str) -> MQTTClient:
    sock = tcp_client_socket("127.0.0.1", broker_port)
    sock.setblocking(False)
    return MQTTClient(
        sock,
        client_id=client_id,
        keep_alive_seconds=30,
        ack_timeout_seconds=5.0,
    )


def _drive_until(
    client: MQTTClient,
    predicate,
    *,
    timeout_seconds: float = 8.0,
) -> bool:
    """Tick the client until *predicate* returns truthy or *timeout* expires."""
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        client.handle(ticks_ms())
        if predicate():
            return True
        time.sleep(0.005)  # 5 ms per tick — fast enough for tests
    return False


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestConnectAgainstMosquitto:
    def test_connect_succeeds(self, mosquitto_broker: int) -> None:
        client = _new_client(mosquitto_broker, "test-connect")
        client.connect()
        assert _drive_until(
            client, lambda: client.state == ProtocolState.CONNECTED,
        ), f"client state stuck at {client.state}: {client.last_error}"
        client.disconnect()


class TestPublishSubscribe:
    def test_qos0_round_trip(self, mosquitto_broker: int) -> None:
        """Same client publishes + subscribes — sees its own message."""
        client = _new_client(mosquitto_broker, "test-qos0")
        client.connect()
        assert _drive_until(client, lambda: client.state == ProtocolState.CONNECTED)

        captured: list[tuple[str, bytes]] = []
        client.on_message = lambda topic, payload: captured.append((topic, payload))

        subscribed: list[bool] = []
        client.subscribe(
            "chumicro-mqtt-test/qos0",
            qos=0,
            on_subscribe=lambda topic, granted: subscribed.append(True),
        )
        assert _drive_until(client, lambda: subscribed)

        client.publish("chumicro-mqtt-test/qos0", b"hello-qos0", qos=0)
        assert _drive_until(client, lambda: captured)
        assert captured[0][0] == "chumicro-mqtt-test/qos0"
        assert captured[0][1] == b"hello-qos0"
        client.disconnect()

    def test_qos1_round_trip(self, mosquitto_broker: int) -> None:
        client = _new_client(mosquitto_broker, "test-qos1")
        client.connect()
        assert _drive_until(client, lambda: client.state == ProtocolState.CONNECTED)

        received: list[tuple[str, bytes]] = []
        client.on_message = lambda topic, payload: received.append((topic, payload))

        subscribed: list[bool] = []
        client.subscribe(
            "chumicro-mqtt-test/qos1",
            qos=1,
            on_subscribe=lambda topic, granted: subscribed.append(True),
        )
        assert _drive_until(client, lambda: subscribed)

        delivered: list[bool] = []
        client.publish(
            "chumicro-mqtt-test/qos1",
            b"hello-qos1",
            qos=1,
            on_publish=lambda topic, payload: delivered.append(True),
        )
        # Both events should fire: PUBACK delivered (publisher
        # callback) AND the broker sends our own QoS 1 message back
        # to us as inbound (reception callback).
        assert _drive_until(client, lambda: delivered and received)
        assert delivered == [True]
        assert received[0][1] == b"hello-qos1"
        client.disconnect()

    def test_concurrent_qos1_publishes(self, mosquitto_broker: int) -> None:
        """Two QoS 1 publishes in flight at once — both PUBACKs fire callbacks."""
        client = _new_client(mosquitto_broker, "test-qos1-concurrent")
        client.connect()
        assert _drive_until(client, lambda: client.state == ProtocolState.CONNECTED)

        first: list[bool] = []
        second: list[bool] = []
        client.publish(
            "chumicro-mqtt-test/concurrent/a",
            b"alpha",
            qos=1,
            on_publish=lambda topic, payload: first.append(True),
        )
        client.publish(
            "chumicro-mqtt-test/concurrent/b",
            b"beta",
            qos=1,
            on_publish=lambda topic, payload: second.append(True),
        )
        assert _drive_until(client, lambda: first and second, timeout_seconds=10.0)
        assert first == [True]
        assert second == [True]
        client.disconnect()


class TestPatternHandlers:
    def test_pattern_handler_dispatches(self, mosquitto_broker: int) -> None:
        client = _new_client(mosquitto_broker, "test-pattern")
        client.connect()
        assert _drive_until(client, lambda: client.state == ProtocolState.CONNECTED)

        sensors: list[str] = []
        client.add_pattern_handler(
            "sensors/+/temperature",
            lambda topic, payload: sensors.append(topic),
        )
        client.subscribe("sensors/#", qos=0)
        assert _drive_until(client, lambda: client.state == ProtocolState.CONNECTED)

        client.publish("sensors/back-porch/temperature", b"21", qos=0)
        client.publish("sensors/kitchen/humidity", b"45", qos=0)
        # Driving for ~1s gives both inbound messages time to land.
        assert _drive_until(client, lambda: sensors, timeout_seconds=3.0)
        # Only the temperature message hit the handler (humidity
        # didn't match the pattern).
        assert sensors == ["sensors/back-porch/temperature"]
        client.disconnect()


class TestRetainedMessages:
    def test_retain_and_replay(self, mosquitto_broker: int) -> None:
        """Publish retain=True; a fresh subscriber gets the retained payload."""
        publisher = _new_client(mosquitto_broker, "test-retain-pub")
        publisher.connect()
        assert _drive_until(
            publisher, lambda: publisher.state == ProtocolState.CONNECTED,
        )
        publisher.publish(
            "chumicro-mqtt-test/retain",
            b"persisted",
            qos=0,
            retain=True,
        )
        # Drive briefly to flush the wire write.
        _drive_until(publisher, lambda: False, timeout_seconds=0.5)
        publisher.disconnect()

        # Fresh subscriber.
        subscriber = _new_client(mosquitto_broker, "test-retain-sub")
        subscriber.connect()
        assert _drive_until(
            subscriber, lambda: subscriber.state == ProtocolState.CONNECTED,
        )
        seen: list[bytes] = []
        subscriber.on_message = lambda topic, payload: seen.append(payload)
        subscriber.subscribe("chumicro-mqtt-test/retain", qos=0)
        assert _drive_until(subscriber, lambda: seen, timeout_seconds=3.0)
        assert seen == [b"persisted"]

        # Cleanup: clear retained by publishing empty.
        cleaner = _new_client(mosquitto_broker, "test-retain-clean")
        cleaner.connect()
        _drive_until(cleaner, lambda: cleaner.state == ProtocolState.CONNECTED)
        cleaner.publish("chumicro-mqtt-test/retain", b"", qos=0, retain=True)
        _drive_until(cleaner, lambda: False, timeout_seconds=0.5)
        cleaner.disconnect()
        subscriber.disconnect()
