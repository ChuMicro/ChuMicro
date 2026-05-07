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

Configuration
=============

Reads the deployed ``runtime_config.msgpack`` (baked from
``secrets.toml`` + per-example ``examples/config.toml`` by the
deploy pipeline) via the flat-key API:

* WiFi: ``WifiConfig.from_config(config)`` reads ``wifi.ssid`` /
  ``wifi.password`` plus optional tunables.
* MQTT: ``MQTTClient.from_config(config, radio=…)`` reads
  ``mqtt.broker.host`` / ``mqtt.broker.port`` / ``mqtt.client_id``
  / ``mqtt.keep_alive_seconds`` plus optional auth.
* App-level (this example's own concerns, not the library's):
  ``telemetry.topic`` / ``telemetry.command_topic`` /
  ``telemetry.sensor_id``.

When ``runtime_config.msgpack`` isn't present (raw single-file
deploys), every value falls back to a hardcoded constant below
— the public ``test.mosquitto.org:1883`` broker, a placeholder
SSID, etc.  Edit the constants before deploying that way.

Deploying
=========

Deploy from a chumicro fork or clone::

    python scripts/run.py deploy-example mqtt circuitpython_telemetry --device <id>

Or from a workspace template repo (for user-authored projects
that follow the same example shape).  Either path composes
``secrets.toml`` + ``examples/config.toml`` into the staged
``runtime_config.msgpack`` and validates against the manifest
union before deploying.

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

from chumicro_config import RuntimeConfig
from chumicro_mqtt import MQTTClient
from chumicro_wifi import WifiConfig, WifiService, WifiState

# Fallback constants — used only when runtime_config.msgpack is absent.
WIFI_SSID = "your-wifi-ssid"  # noqa: S105 — replace before deploying
WIFI_PASSWORD = "your-wifi-password"  # noqa: S105 — replace before deploying
TOPIC = "chumicro-demo/telemetry"
COMMAND_TOPIC = "chumicro-demo/cmd"
SENSOR_ID = "demo-temp"
PUBLISH_INTERVAL_S = 5


def _load_runtime_config():
    """Return the deployed RuntimeConfig, or ``None`` when absent."""
    try:
        from chumicro_config import load_runtime_config
        return load_runtime_config()
    except (ImportError, OSError):
        return None


# ---------------------------------------------------------------------------
# Wifi up.
# ---------------------------------------------------------------------------

config = _load_runtime_config()
wifi_config = WifiConfig.try_from_config(config) if config is not None else None
if wifi_config is None:
    wifi_config = WifiConfig(
        ssid=WIFI_SSID,
        password=WIFI_PASSWORD,
        connect_timeout_ms=15_000,
    )

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

# App-level settings (this example's concerns, not in mqtt's manifest).
if config is not None:
    topic = config.get("telemetry.topic", TOPIC)
    command_topic = config.get("telemetry.command_topic", COMMAND_TOPIC)
    sensor_id = config.get("telemetry.sensor_id", SENSOR_ID)
else:
    topic = TOPIC
    command_topic = COMMAND_TOPIC
    sensor_id = SENSOR_ID

# Build the client.  When config is None, from_config receives an empty
# RuntimeConfig and the library defaults apply (test.mosquitto.org:1883,
# auto-derived client_id, 60 s keepalive).
mqtt = MQTTClient.from_config(config or RuntimeConfig({}), radio=wifi_radio)


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

# Resolve broker host/port for the status print (the client already
# has the connected socket; we re-read config for display).
if config is not None:
    broker_host = config.get("mqtt.broker.host", "test.mosquitto.org")
    broker_port = config.get("mqtt.broker.port", 1883)
else:
    broker_host = "test.mosquitto.org"
    broker_port = 1883

print(f"MQTT_CONNECTED broker={broker_host}:{broker_port}")

mqtt.subscribe(command_topic, qos=1)
print(f"Subscribed to {command_topic}")


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
        "sensor": sensor_id,
        "value": _synthetic_reading(elapsed),
        "uptime_s": round(elapsed, 1),
    })

    publish_done = [False]
    mqtt.publish(
        topic,
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
