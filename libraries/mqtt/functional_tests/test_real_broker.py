"""Real-network acceptance for chumicro-mqtt.

Category 1 — host-side Mosquitto fixture.

Brings wifi up on the device, connects to the Mosquitto broker the
conftest spawned on the LAN, publishes + subscribes on a unique
topic, asserts the QoS 1 PUBLISH round-trips back. Cooperates with
an LED-blink counter on the same loop to verify the publish path
doesn't block the runner.

Skipped at collection time when no credentials are configured. The
conftest's `set_runtime_config(..., required_keys=...)` declares
`wifi.ssid` / `wifi.password` / `mqtt.broker.host` /
`mqtt.broker.port` as required; the host plugin applies
`pytest.mark.skip` before deploy when any are missing. Credentials +
broker host/port ship as `/runtime_config.msgpack`, read on-device
through the harness helper.
"""

import time

from chumicro_mqtt import MQTTClient
from chumicro_sockets import tcp_client_socket
from chumicro_test_harness.network import runtime_config, wifi_up
from chumicro_timing import ticks_ms

_DEADLINE_MS = 30_000


def _sleep_ms(duration_ms: int) -> None:
    runtime_sleep_ms = getattr(time, "sleep_ms", None)
    if callable(runtime_sleep_ms):
        runtime_sleep_ms(duration_ms)
        return
    time.sleep(duration_ms / 1000)


def _unique_topic_root() -> str:
    """Per-run topic prefix that avoids colliding with parallel test runs.

    Suffix is the low six digits of `ticks_ms`, which the cross-runtime
    tick contract guarantees on CP / MP / CPython.
    """
    return f"chumicro-test/run-{ticks_ms() % 1_000_000}"


def test_real_mqtt_publish_subscribe_round_trip() -> None:
    """Connect to the broker, publish QoS 1, confirm the same payload comes back."""
    config = runtime_config()
    ssid = config.get("wifi.ssid", "")
    password = config.get("wifi.password", "")
    broker_host = config.get("mqtt.broker.host")
    broker_port = config.get("mqtt.broker.port")
    if not ssid or broker_host is None or broker_port is None:
        raise AssertionError(
            "wifi or broker runtime config missing — the conftest's "
            "`set_runtime_config(..., required_keys=...)` should have "
            "skipped this test at collection time. Reaching this body "
            "means the conftest's required_keys list is incomplete.",
        )

    radio, ip = wifi_up(ssid, password)
    print(f"WIFI_OK ip={ip}")

    sock = tcp_client_socket(broker_host, broker_port, radio=radio)
    client = MQTTClient(
        sock,
        client_id=f"chumicro-test-{ticks_ms() % 1_000_000_000}",
        keep_alive_seconds=30,
    )

    received: list[tuple[str, bytes]] = []

    def remember(topic, payload):
        # MP / CP MQTT deliver topic as `str` and payload as `bytes` /
        # `bytearray`. Coerce to (str, bytes) so assertions don't have
        # to handle either form.
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

    # Connect. Heartbeat-print every ~1 s so the host's idle-timeout
    # doesn't fire during legitimate slow CONNACK waits on CP boards
    # (the wifi + TCP + MQTT CONNECT-CONNACK chain can spend several
    # seconds in non-blocking recv polls before the broker replies).
    print("MQTT_CONNECTING")
    client.connect()
    deadline = ticks_ms() + _DEADLINE_MS
    poll_count = 0
    while client.state != "connected":
        if ticks_ms() > deadline:
            raise AssertionError(
                f"MQTT CONNECT did not complete in time; "
                f"state={client.state} last_error={client.last_error!r}",
            )
        if client.state == "failed":
            raise AssertionError(
                f"MQTT CONNECT failed; last_error={client.last_error!r}",
            )
        if client.check(ticks_ms()):
            client.handle(ticks_ms())
        poll_count += 1
        if poll_count % 50 == 0:
            print(f"MQTT_POLL count={poll_count} state={client.state}")
        _sleep_ms(20)
    print(f"MQTT_CONNECTED after {poll_count} polls")

    client.subscribe(topic, qos=1)

    publish_complete = [False]

    def on_publish_done(_topic, _payload):
        publish_complete[0] = True

    client.publish(topic, payload, qos=1, on_publish=on_publish_done)

    # Drive both round-trips with the LED-blink invariant.
    led_counter = 0
    deadline = ticks_ms() + _DEADLINE_MS
    while not (publish_complete[0] and received):
        if ticks_ms() > deadline:
            raise AssertionError(
                f"publish/subscribe round-trip did not complete in "
                f"{_DEADLINE_MS} ms; published={publish_complete[0]}, "
                f"received_count={len(received)}",
            )
        if client.check(ticks_ms()):
            client.handle(ticks_ms())
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
