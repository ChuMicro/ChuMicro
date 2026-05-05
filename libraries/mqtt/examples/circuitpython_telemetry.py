"""Periodic MQTT telemetry on a real CircuitPython / MicroPython board.

Brings wifi up, connects to a configured MQTT broker, publishes a
synthetic reading to ``<topic>`` every ``PUBLISH_INTERVAL_S``
seconds with QoS 1.  Subscribes to a control topic alongside so
the device receives commands inbound — round-trip proof, not
publish-only fire-and-forget.

Demonstrates the runner-shaped client driving real MQTT traffic
while a simple LED-style counter keeps incrementing — proof that
the in-flight publish never block-calls the loop while waiting
for PUBACK.

WiFi + broker config
====================

Reads from ``runtime_config.msgpack`` (baked from workspace.local.yml
by ``chumicro-workspace``):

* ``[wifi]`` — SSID + password
* ``[telemetry]`` — broker host + port + topic + sensor_id +
  client_id

Falls back to the constants below for raw single-file deploys.

The default broker is ``test.mosquitto.org:1883`` — the public
test broker that's been online since 2008.  No auth, no TLS.
Don't ship secrets through it; for production workloads point at
your own broker via ``runtime_config.msgpack``.

Deploying
=========

Recommended (workspace-managed)::

    chumicro-workspace deploy --thing telemetry

Raw (single-file copy)::

    1. Edit WIFI_SSID, WIFI_PASSWORD, BROKER_HOST below.
    2. Copy this file as ``/code.py`` (CP) or ``/main.py`` (MP).
    3. Ensure chumicro-{wifi,sockets,mqtt,config,timing,runner,
       msgpack} are present under ``/lib/``.

Example output::

    ADAPTER: cp
    WIFI_OK ip=10.0.0.42
    MQTT_CONNECTED broker=test.mosquitto.org:1883
    Subscribed to chumicro-demo/cmd
    [tx 1] {"sensor": "demo-temp", "value": 21.4} led_ticks=27
    [tx 2] {"sensor": "demo-temp", "value": 21.6} led_ticks=24
    [rx]  chumicro-demo/cmd <- b'ping'
"""

import json
import math
import sys
import time

from chumicro_mqtt import MQTTClient
from chumicro_sockets import tcp_client_socket
from chumicro_wifi import WifiConfig, WifiService, WifiState

# Fallback constants — used only when runtime_config.msgpack absent.
WIFI_SSID = "your-wifi-ssid"  # noqa: S105 — replace before deploying
WIFI_PASSWORD = "your-wifi-password"  # noqa: S105 — replace before deploying
BROKER_HOST = "test.mosquitto.org"
BROKER_PORT = 1883
TOPIC = "chumicro-demo/telemetry"
COMMAND_TOPIC = "chumicro-demo/cmd"
SENSOR_ID = "demo-temp"
CLIENT_ID = "chumicro-telemetry-example"
PUBLISH_INTERVAL_S = 5
KEEPALIVE_S = 30


def _load_runtime_settings():
    """Return resolved wifi + telemetry settings."""
    wifi_config = None
    settings = {
        "broker_host": BROKER_HOST,
        "broker_port": BROKER_PORT,
        "topic": TOPIC,
        "command_topic": COMMAND_TOPIC,
        "sensor_id": SENSOR_ID,
        "client_id": CLIENT_ID,
    }
    try:
        from chumicro_config import load_runtime_config

        config = load_runtime_config()
        if config:
            wifi_section = config.get("wifi")
            if wifi_section:
                wifi_config = WifiConfig.from_dict(wifi_section)
            telemetry_section = config.get("telemetry", {})
            for key in settings:
                if key in telemetry_section:
                    settings[key] = telemetry_section[key]
    except (ImportError, OSError):
        pass
    if wifi_config is None:
        wifi_config = WifiConfig(
            ssid=WIFI_SSID,
            password=WIFI_PASSWORD,
            connect_timeout_ms=15_000,
        )
    return wifi_config, settings


# ---------------------------------------------------------------------------
# Wifi up.
# ---------------------------------------------------------------------------

wifi_config, settings = _load_runtime_settings()
service = WifiService(wifi_config)


def _drive_until(predicate, deadline_ms):
    start = service._ticks_ms()  # noqa: SLF001
    while not predicate():
        now = service._ticks_ms()  # noqa: SLF001
        if service._ticks_diff(now, start) >= deadline_ms:  # noqa: SLF001
            return False
        if service.check(now):
            service.handle(now)
        time.sleep(0.05)
    return True


print(f"ADAPTER: {service.adapter_name}")
print("Connecting to wifi...")
if not _drive_until(lambda: service.state == WifiState.CONNECTED, 15_000):
    print("STATUS: FAIL_WIFI")
    print("ERROR:", service.last_error)
    raise SystemExit(1)
print(f"WIFI_OK ip={service.ip}")

wifi_radio = None
if sys.implementation.name == "circuitpython":
    radio_owner = getattr(service, "_adapter", None)
    wifi_radio = getattr(radio_owner, "_radio", None)
    if wifi_radio is None:
        import wifi as _wifi
        wifi_radio = _wifi.radio


# ---------------------------------------------------------------------------
# MQTT connect + subscribe.
# ---------------------------------------------------------------------------

sock = tcp_client_socket(
    settings["broker_host"], settings["broker_port"], radio=wifi_radio,
)
mqtt = MQTTClient(
    sock,
    client_id=settings["client_id"],
    keepalive_secs=KEEPALIVE_S,
)


def on_message(topic, payload):
    print(f"[rx]  {topic} <- {payload!r}")


mqtt.on_message = on_message
mqtt.connect()


def _drive_mqtt_until(predicate, deadline_ms):
    start = service._ticks_ms()  # noqa: SLF001
    while not predicate():
        now = service._ticks_ms()  # noqa: SLF001
        if service._ticks_diff(now, start) >= deadline_ms:  # noqa: SLF001
            return False
        if service.check(now):
            service.handle(now)
        if mqtt.check(now):
            mqtt.handle(now)
        time.sleep(0.02)
    return True


if not _drive_mqtt_until(mqtt.is_connected, 15_000):
    print("STATUS: FAIL_MQTT_CONNECT")
    raise SystemExit(1)

print(
    f"MQTT_CONNECTED broker={settings['broker_host']}:"
    f"{settings['broker_port']}",
)

mqtt.subscribe(settings["command_topic"], qos=1)
print(f"Subscribed to {settings['command_topic']}")


# ---------------------------------------------------------------------------
# Publish loop.
# ---------------------------------------------------------------------------


def _synthetic_reading(elapsed_seconds: float) -> float:
    """Synthetic sine-wave reading; replace with your real sensor."""
    return round(20.0 + 5.0 * math.sin(elapsed_seconds / 30.0), 2)


attempt = 0
start_seconds = time.monotonic()

while True:
    attempt += 1
    elapsed = time.monotonic() - start_seconds
    payload = json.dumps({
        "sensor": settings["sensor_id"],
        "value": _synthetic_reading(elapsed),
        "uptime_s": round(elapsed, 1),
    })

    publish_done = [False]
    mqtt.publish(
        settings["topic"],
        payload.encode(),
        qos=1,
        on_publish=lambda _packet_id, flag=publish_done: flag.__setitem__(0, True),
    )

    led_counter = 0
    while not publish_done[0]:
        now = service._ticks_ms()  # noqa: SLF001
        if service.check(now):
            service.handle(now)
        if mqtt.check(now):
            mqtt.handle(now)
        led_counter += 1
        time.sleep(0.02)

    print(f"[tx {attempt}] {payload} led_ticks={led_counter}")

    # Wait for the next interval; keep ticking wifi + mqtt so we
    # process inbound subscribes + keepalive.
    next_at = time.monotonic() + PUBLISH_INTERVAL_S
    while time.monotonic() < next_at:
        now = service._ticks_ms()  # noqa: SLF001
        if service.check(now):
            service.handle(now)
        if mqtt.check(now):
            mqtt.handle(now)
        time.sleep(0.02)
