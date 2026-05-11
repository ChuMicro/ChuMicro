"""Periodic MQTT telemetry on a real CircuitPython / MicroPython board.

Brings wifi up via the local ``helpers`` module, connects to a
configured MQTT broker, publishes a synthetic reading to ``<topic>``
every ``PUBLISH_INTERVAL_S`` seconds with QoS 1.  Subscribes to a
control topic alongside so the device receives commands inbound —
round-trip proof, not publish-only fire-and-forget.

Demonstrates the runner-shaped client driving real MQTT traffic
while a simple LED-style counter keeps incrementing — proof that
the in-flight publish never block-calls the loop while waiting
for PUBACK.

Configuration
=============

Reads the deployed ``runtime_config.msgpack`` (baked from
``secrets.toml`` + per-example ``examples/config.toml`` by the
deploy pipeline) via the flat-key API:

* WiFi (read by ``helpers.wifi_up``): ``wifi.ssid`` / ``wifi.password``.
* MQTT (read by ``MQTTClient.from_config``): ``mqtt.broker.host`` /
  ``mqtt.broker.port`` / ``mqtt.client_id`` / ``mqtt.keep_alive_seconds``
  plus optional auth.
* App-level (this example's own concerns, not the library's):
  ``telemetry.topic`` / ``telemetry.command_topic`` /
  ``telemetry.sensor_id``.

When ``runtime_config.msgpack`` isn't present (raw single-file
deploys), wifi creds fall back to the placeholder constants below
— edit them first.  The MQTT broker has no fallback: set
``BROKER_HOST`` and ``BROKER_PORT`` (raw deploy) or
``mqtt.broker.host`` / ``mqtt.broker.port`` in your
``runtime_config.msgpack`` (workspace deploy) before running.  The
library refuses to silently dial a third-party broker on your behalf.

Deploying
=========

Deploy with ``chumicro-workspace``::

    chumicro-workspace deploy-example mqtt telemetry --device <id>

Example output::

    WIFI_OK ip=10.0.0.42
    MQTT_CONNECTED broker=10.0.0.5:1883
    Subscribed to chumicro-demo/cmd
    [tx 1] {"sensor": "demo-temp", "value": 21.4} led_ticks=27
    [tx 2] {"sensor": "demo-temp", "value": 21.6} led_ticks=24
    [rx]  chumicro-demo/cmd <- b'ping'
"""

#: Cross-runtime — wifi-up via :mod:`helpers` dispatches per
#: ``sys.implementation.name`` (CP / MP) and the MQTT client is
#: pure-Python.  The marker tells :func:`scripts.verify_examples`
#: + ``deploy-example`` to allow this file on either runtime.
__chumicro_runtimes__ = ("circuitpython", "micropython")

import json
import math
import time

from chumicro_mqtt import MQTTClient, ProtocolState
from helpers import runtime_config, ticks_add, ticks_diff, ticks_ms, wifi_up

WIFI_SSID = "your-wifi-ssid"  # noqa: S105 — replace before deploying
WIFI_PASSWORD = "your-wifi-password"  # noqa: S105 — replace before deploying
BROKER_HOST = ""  # required for raw single-file deploys; e.g. "10.0.0.5"
BROKER_PORT = 1883
TOPIC = "chumicro-demo/telemetry"
COMMAND_TOPIC = "chumicro-demo/cmd"
SENSOR_ID = "demo-temp"
PUBLISH_INTERVAL_S = 5

config = runtime_config()
radio, ip = wifi_up(WIFI_SSID, WIFI_PASSWORD)
print(f"WIFI_OK ip={ip}")

topic = config.get("telemetry.topic", TOPIC)
command_topic = config.get("telemetry.command_topic", COMMAND_TOPIC)
sensor_id = config.get("telemetry.sensor_id", SENSOR_ID)

# Resolve broker host/port from config first, then example constants —
# MQTTClient.from_config refuses to construct without them, so the
# dial-target is loud, not implicit.
if "mqtt.broker.host" not in config:
    if not BROKER_HOST:
        print("STATUS: FAIL_MQTT_BROKER_NOT_CONFIGURED")
        print("ERROR: set mqtt.broker.host in runtime_config.msgpack "
              "or BROKER_HOST in this file before deploying.")
        raise SystemExit(1)
    config["mqtt.broker.host"] = BROKER_HOST
    config["mqtt.broker.port"] = BROKER_PORT

mqtt = MQTTClient.from_config(config, radio=radio)


def on_message(topic, payload):
    print(f"[rx]  {topic} <- {payload!r}")


mqtt.on_message = on_message
mqtt.connect()


def _drive_until(predicate, deadline_ms):
    deadline = ticks_add(ticks_ms(), deadline_ms)
    while not predicate():
        if ticks_diff(deadline, ticks_ms()) <= 0:
            return False
        if mqtt.check(ticks_ms()):
            mqtt.handle(ticks_ms())
        time.sleep(0.02)
    return True


if not _drive_until(lambda: mqtt.state == ProtocolState.CONNECTED, 15_000):
    print("STATUS: FAIL_MQTT_CONNECT")
    raise SystemExit(1)

print(f"MQTT_CONNECTED broker={config['mqtt.broker.host']}:{config['mqtt.broker.port']}")

mqtt.subscribe(command_topic, qos=1)
print(f"Subscribed to {command_topic}")


def _synthetic_reading(elapsed_seconds: float) -> float:
    """Synthetic sine-wave reading; replace with your real sensor."""
    return round(20.0 + 5.0 * math.sin(elapsed_seconds / 30.0), 2)


attempt = 0
start_ticks = ticks_ms()

while True:
    attempt += 1
    elapsed_s = ticks_diff(ticks_ms(), start_ticks) / 1000
    payload = json.dumps({
        "sensor": sensor_id,
        "value": _synthetic_reading(elapsed_s),
        "uptime_s": round(elapsed_s, 1),
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
        if mqtt.check(ticks_ms()):
            mqtt.handle(ticks_ms())
        led_counter += 1
        time.sleep(0.02)

    print(f"[tx {attempt}] {payload} led_ticks={led_counter}")

    next_due = ticks_add(ticks_ms(), PUBLISH_INTERVAL_S * 1000)
    while ticks_diff(next_due, ticks_ms()) > 0:
        if mqtt.check(ticks_ms()):
            mqtt.handle(ticks_ms())
        time.sleep(0.02)
