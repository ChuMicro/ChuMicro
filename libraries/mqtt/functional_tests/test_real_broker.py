"""Real-network acceptance for chumicro-mqtt.

End-to-end: bring wifi up on the device, connect to a public MQTT
broker, publish + subscribe to a unique topic, verify the inbound
PUBLISH round-trips back via QoS 1.

Skips silently when no credentials are configured (see
``conftest.py`` for the ``_test_creds`` shim materialised from
the top-level ``chumicro-dev-config.toml``).

Verifies the canonical promise (Decision 0014): an LED-style
counter keeps incrementing on the same loop while the publish is
in flight and waiting for PUBACK.

Broker
======

``test.mosquitto.org:1883`` (plain MQTT, no auth) — the widely-used
public test broker that's been online since 2008.  No creds, no
TLS, intended for exactly this kind of acceptance test.  Topics
are namespaced ``chumicro-test/<unique>/...`` so we don't collide
with anyone else's experiments.

If the broker is unreachable from the device's network, the test
fails with a clear timeout — that's a real network issue, not a
test bug.
"""

import sys
import time

from chumicro_mqtt import MQTTClient
from chumicro_sockets import tcp_client_socket
from chumicro_wifi import WifiConfig, WifiService, WifiState

try:
    from _test_creds import PASSWORD, SSID
    _HAS_CREDS = True
except ImportError:
    SSID = ""
    PASSWORD = ""
    _HAS_CREDS = False


_IS_DEVICE_RUNTIME = sys.implementation.name in ("circuitpython", "micropython")
_BROKER_HOST = "test.mosquitto.org"
_BROKER_PORT = 1883
_DEADLINE_MS = 30_000
_WIFI_CONNECT_TIMEOUT_MS = 15_000


def _sleep_ms(duration_ms: int) -> None:
    runtime_sleep_ms = getattr(time, "sleep_ms", None)
    if callable(runtime_sleep_ms):
        runtime_sleep_ms(duration_ms)
        return
    time.sleep(duration_ms / 1000)


def _ticks_ms() -> int:
    runtime_ticks_ms = getattr(time, "ticks_ms", None)
    if callable(runtime_ticks_ms):
        return runtime_ticks_ms()
    return int(time.monotonic() * 1000)


def _bring_wifi_up() -> WifiService:
    wifi = WifiService(
        WifiConfig(
            ssid=SSID,
            password=PASSWORD,
            connect_timeout_ms=_WIFI_CONNECT_TIMEOUT_MS,
        ),
    )
    deadline = _ticks_ms() + _WIFI_CONNECT_TIMEOUT_MS
    while wifi.state != WifiState.CONNECTED:
        if _ticks_ms() > deadline:
            raise AssertionError(
                f"wifi did not link within "
                f"{_WIFI_CONNECT_TIMEOUT_MS} ms; state={wifi.state}",
            )
        if wifi.check(_ticks_ms()):
            wifi.handle(_ticks_ms())
        _sleep_ms(50)
    return wifi


def _unique_topic_root() -> str:
    """Per-run topic prefix to avoid colliding with other test instances.

    Uses ``time.monotonic_ns`` (CP/MP/CPython all expose it) modded
    so the suffix fits in a tidy string.
    """
    return f"chumicro-test/run-{time.monotonic_ns() % 1_000_000}"


def test_real_mqtt_publish_subscribe_round_trip() -> None:
    """Connect to a real broker, publish QoS 1, confirm receipt."""
    if not (_HAS_CREDS and _IS_DEVICE_RUNTIME):
        return

    wifi = _bring_wifi_up()
    print(f"WIFI_OK ip={wifi.ip}")

    sock = tcp_client_socket(
        _BROKER_HOST,
        _BROKER_PORT,
        radio=wifi.adapter.radio,
    )
    client = MQTTClient(
        sock,
        client_id=f"chumicro-test-{time.monotonic_ns() % 1_000_000_000}",
        keepalive_secs=30,
    )

    received: list[tuple[bytes, bytes]] = []

    def remember(topic, payload):
        received.append((bytes(topic), bytes(payload)))

    client.on_message = remember

    topic_root = _unique_topic_root()
    topic = f"{topic_root}/echo"
    payload = b"hello from chumicro acceptance"

    # Connect.
    client.connect()
    deadline = _ticks_ms() + _DEADLINE_MS
    while not client.is_connected():
        if _ticks_ms() > deadline:
            raise AssertionError("MQTT CONNECT did not complete in time")
        if client.check(_ticks_ms()):
            client.handle(_ticks_ms())
        _sleep_ms(20)
    print("MQTT_CONNECTED")

    # Subscribe.
    client.subscribe(topic, qos=1)

    # Publish QoS 1.
    publish_complete = [False]

    def on_publish_done(packet_id):  # noqa: ARG001 - pid unused
        publish_complete[0] = True

    client.publish(topic, payload, qos=1, on_publish=on_publish_done)

    # Drive both round-trips with the LED-blink invariant.
    led_counter = 0
    deadline = _ticks_ms() + _DEADLINE_MS
    while not (publish_complete[0] and received):
        if _ticks_ms() > deadline:
            raise AssertionError(
                f"publish/subscribe round-trip did not complete in "
                f"{_DEADLINE_MS} ms; published={publish_complete[0]}, "
                f"received_count={len(received)}",
            )
        if wifi.check(_ticks_ms()):
            wifi.handle(_ticks_ms())
        if client.check(_ticks_ms()):
            client.handle(_ticks_ms())
        led_counter += 1
        _sleep_ms(20)

    print(
        f"MQTT_OK led_ticks={led_counter} received={len(received)} "
        f"first_topic={received[0][0]!r}",
    )

    assert publish_complete[0], "QoS 1 publish never got PUBACK"
    assert any(
        topic_recvd.decode() == topic and payload_recvd == payload
        for topic_recvd, payload_recvd in received
    ), f"did not receive own publish back; received={received}"
    assert led_counter > 5, (
        f"LED counter only ticked {led_counter} times — somebody "
        f"block-called during the round-trip"
    )

    client.disconnect()


def test_real_mqtt_skip_when_no_creds_configured() -> None:
    """Document the no-creds path; always passes."""
    if _HAS_CREDS:
        return
