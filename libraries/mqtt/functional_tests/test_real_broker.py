"""Real-network acceptance for chumicro-mqtt.

End-to-end: bring wifi up on the device, connect to a configured
MQTT broker, publish + subscribe to a unique topic, verify the
inbound PUBLISH round-trips back via QoS 1.

Skipped at collection time when no credentials are configured —
the conftest's ``set_runtime_config(..., required_keys=...)`` declares
``wifi.ssid`` / ``wifi.password`` / ``mqtt.broker.host`` /
``mqtt.broker.port`` as required, so the host plugin applies
``pytest.mark.skip`` with a clear message before deploy.  Credentials +
the broker host/port ship from the host conftest as
``/runtime_config.msgpack`` and are read here via
``chumicro_config.load_runtime_config()``.

Verifies the LED-blink invariant on a real board: an LED-style
counter keeps incrementing on the same loop while the publish is
in flight and waiting for PUBACK.

Broker
======

The conftest spawns a host-side Mosquitto broker on the LAN when
``mosquitto`` is on ``PATH``; otherwise the test uses whatever
``mqtt.broker.host`` / ``mqtt.broker.port`` the user has set in
``secrets.toml`` / per-library ``config.toml``.  Topics are
namespaced ``chumicro-test/<unique>/...`` so we don't collide with
anyone else's experiments.

If the broker is unreachable from the device's network, the test
fails with a clear timeout — that's a real network issue, not a
test bug.
"""

import time

from chumicro_config import config
from chumicro_mqtt import MQTTClient
from chumicro_sockets import tcp_client_socket
from chumicro_timing import ticks_ms as _chumicro_ticks_ms
from chumicro_wifi import WifiConfig, WifiService, WifiState

_DEADLINE_MS = 30_000
_WIFI_CONNECT_TIMEOUT_MS = 15_000


def _sleep_ms(duration_ms: int) -> None:
    runtime_sleep_ms = getattr(time, "sleep_ms", None)
    if callable(runtime_sleep_ms):
        runtime_sleep_ms(duration_ms)
        return
    time.sleep(duration_ms / 1000)


#: Use chumicro-timing's ``ticks_ms`` rather than a per-test-file
#: shim so the value we feed into ``MQTTClient.handle(now_ms)`` is in
#: the same time domain as the deadlines the client computes
#: internally.  On CircuitPython, ``time.ticks_ms`` does not exist —
#: a naive ``time.monotonic() * 1000`` shim returns an unwrapped
#: float-derived ms count, while ``chumicro-timing`` resolves to
#: ``supervisor.ticks_ms`` which is 29-bit-wrapped (the portable
#: tick contract ``chumicro-timing`` exposes).  Mixing the two on CP makes
#: ``ticks_diff(deadline, now_ms)`` go negative on the first tick
#: and the client immediately reports "timed out awaiting connack".
_ticks_ms = _chumicro_ticks_ms


def _bring_wifi_up(wifi_config: WifiConfig) -> WifiService:
    wifi_config.connect_timeout_ms = _WIFI_CONNECT_TIMEOUT_MS
    wifi = WifiService(wifi_config)
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
    return f"chumicro-test/run-{_ticks_ms() % 1_000_000}"


def test_real_mqtt_publish_subscribe_round_trip() -> None:
    """Connect to a real broker, publish QoS 1, confirm receipt."""
    wifi_cfg = WifiConfig.try_from_config(config)
    if wifi_cfg is None:
        raise AssertionError(
            "wifi runtime config missing — the conftest's "
            "`set_runtime_config(..., required_keys=...)` should have "
            "skipped this test at collection time.  Reaching this body "
            "means the conftest's required_keys list is incomplete.",
        )
    broker_host = config["mqtt.broker.host"]
    broker_port = config["mqtt.broker.port"]

    wifi = _bring_wifi_up(wifi_cfg)
    print(f"WIFI_OK ip={wifi.ip}")

    sock = tcp_client_socket(
        broker_host,
        broker_port,
        radio=wifi.adapter.radio,
    )
    client = MQTTClient(
        sock,
        client_id=f"chumicro-test-{_ticks_ms() % 1_000_000_000}",
        keep_alive_seconds=30,
    )

    received: list[tuple[str, bytes]] = []

    def remember(topic, payload):
        # MP/CP MQTT delivers topic as ``str`` and payload as
        # ``bytes`` / ``bytearray``; coerce to uniform (str, bytes)
        # so assertions don't have to handle either form.
        topic_str = topic.decode() if isinstance(topic, (bytes, bytearray)) else topic
        payload_bytes = (
            payload if isinstance(payload, bytes)
            else bytes(payload) if isinstance(payload, bytearray)
            else payload.encode()
        )
        received.append((topic_str, payload_bytes))

    client.on_message = remember

    topic_root = _unique_topic_root()
    topic = f"{topic_root}/echo"
    payload = b"hello from chumicro acceptance"

    # Connect.  Emit a heartbeat print every ~1 s so the host's
    # idle-timeout doesn't fire during legitimate slow CONNACK waits
    # on CP boards (where the wifi, TCP, and MQTT CONNECT-CONNACK
    # chain can spend several seconds in non-blocking recv polls
    # before the broker's reply arrives).
    print("MQTT_CONNECTING")
    client.connect()
    deadline = _ticks_ms() + _DEADLINE_MS
    poll_count = 0
    while client.state != "connected":
        if _ticks_ms() > deadline:
            raise AssertionError(
                f"MQTT CONNECT did not complete in time; "
                f"state={client.state} last_error={client.last_error!r}",
            )
        if client.state == "failed":
            raise AssertionError(
                f"MQTT CONNECT failed; last_error={client.last_error!r}",
            )
        if client.check(_ticks_ms()):
            client.handle(_ticks_ms())
        poll_count += 1
        if poll_count % 50 == 0:
            print(f"MQTT_POLL count={poll_count} state={client.state}")
        _sleep_ms(20)
    print(f"MQTT_CONNECTED after {poll_count} polls")

    # Subscribe.
    client.subscribe(topic, qos=1)

    # Publish QoS 1.
    publish_complete = [False]

    def on_publish_done(_topic, _payload):
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
        topic_recvd == topic and payload_recvd == payload
        for topic_recvd, payload_recvd in received
    ), f"did not receive own publish back; received={received}"
    assert led_counter >= 1, (
        "LED counter never incremented — runner loop didn't run; "
        "somebody block-called during the round-trip"
    )

    client.disconnect()
