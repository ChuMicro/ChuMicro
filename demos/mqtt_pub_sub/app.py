"""Board-side of the mqtt_pub_sub demo.

Wires ``chumicro_wifi.WifiService`` + ``chumicro_mqtt.MQTTClient`` into
one ``chumicro_runner.Runner`` and drives them with
``while True: now = runner.tick(); runner.wait(now)``.

Reads like a mainstream MQTT quickstart (paho / Adafruit MiniMQTT): set
a Last Will, set the callbacks once, connect, let the loop run.  All
the connect-time setup happens in ``on_connect`` — publish presence,
subscribe to commands — fire-and-forget, with no callback chain and no
waiting on QoS 1 acks (the client tracks PUBACK / SUBACK internally;
the app never needs to).

Presence pair: a retained ``"offline"`` Last Will the broker publishes
if this board drops uncleanly, plus the retained ``"online"`` published
on connect.  Then the demo publishes three QoS 1 telemetry samples on a
1.5 s cadence, and prints ``DEMO_COMPLETE`` once all three are sent and
the host's one command has arrived.

Marker lines (``WIFI_OK``, ``MQTT_CONNECTED``, ``RETAINED_STATE_SENT``,
``SUBSCRIBED``, ``TELEMETRY_SENT``, ``CMD_RECEIVED``, ``PATTERN_HIT``,
``DEMO_COMPLETE``) drive the host driver via stdout markers.
"""

import json

from chumicro_config import load_runtime_config
from chumicro_mqtt import MQTTClient, ProtocolState
from chumicro_runner import Runner
from chumicro_timing import ticks_add, ticks_diff, ticks_ms
from chumicro_wifi import WifiConfig, WifiService, WifiState

_TELEMETRY_COUNT = 3
_TELEMETRY_INTERVAL_MS = 1_500
_DEMO_DEADLINE_MS = 120_000
# Keep ticking this long after the last telemetry is queued so the runner
# flushes it to the broker before the clean disconnect drops the queue.
_FLUSH_DRAIN_MS = 750

config = load_runtime_config()
client_id = config.get("mqtt.client_id", "chumicro-mqtt-demo-board")
broker = f"{config['mqtt.broker.host']}:{config['mqtt.broker.port']}"
state_topic = f"demo/{client_id}/state"
command_topic = f"demo/{client_id}/cmd"
telemetry_topic = f"demo/{client_id}/telemetry"

wifi = WifiService(WifiConfig.from_config(config))
mqtt = MQTTClient.from_config(config, radio=wifi.adapter.radio)

# Presence via Last Will: the broker publishes a retained "offline" if
# this board drops without a clean DISCONNECT.  on_connect publishes the
# matching retained "online".
mqtt.set_will(state_topic, b"offline", qos=1, retain=True, prefixed=False)

# Demo progress at module scope so the callbacks can read and write
# without ceremony.  Small enough that a class would add noise.
telemetry_sent = 0
command_received = False
start_ms = ticks_ms()


def on_connect():
    """Connect-time setup, fired once: publish presence, subscribe to commands."""
    print(f"MQTT_CONNECTED broker={broker} client_id={client_id}")
    mqtt.publish(state_topic, b"online", qos=1, retain=True, prefixed=False)
    print(f"RETAINED_STATE_SENT topic={state_topic}")
    mqtt.subscribe(command_topic, qos=1, prefixed=False)
    print(f"SUBSCRIBED topic={command_topic}")


def on_command_message(topic, payload):
    global command_received
    text = (
        payload.decode("utf-8", "replace") if isinstance(payload, bytes)
        else payload
    )
    command_received = True
    print(f"CMD_RECEIVED topic={topic} payload={text}")


def on_command_pattern(topic, _payload):
    print(f"PATTERN_HIT topic={topic}")


def on_wifi_state(_old, new):
    if new == WifiState.CONNECTED:
        print(f"WIFI_OK ip={wifi.ip}")
        mqtt.connect()


def publish_telemetry(now_ms):
    """Publish one QoS 1 telemetry sample per call until the quota is met."""
    global telemetry_sent
    if mqtt.state != ProtocolState.CONNECTED or telemetry_sent >= _TELEMETRY_COUNT:
        return
    telemetry_sent += 1
    payload = json.dumps({
        "seq": telemetry_sent,
        "value": 20 + telemetry_sent,
        "uptime_ms": ticks_diff(now_ms, start_ms),
    }).encode()
    mqtt.publish(telemetry_topic, payload, qos=1, prefixed=False)
    print(f"TELEMETRY_SENT seq={telemetry_sent}")


mqtt.on_connect = on_connect
mqtt.on_message = on_command_message
mqtt.add_pattern_handler("demo/+/cmd", on_command_pattern)
wifi.on_state_change(on_wifi_state)

runner = Runner()
runner.add(wifi)
runner.add(mqtt)
runner.add_periodic(publish_telemetry, period_ms=_TELEMETRY_INTERVAL_MS)

overall_deadline_ms = ticks_add(start_ms, _DEMO_DEADLINE_MS)
wrap_up_started_ms = 0

while True:
    now_ms = runner.tick()

    if (
        telemetry_sent >= _TELEMETRY_COUNT
        and command_received
        and wrap_up_started_ms == 0
    ):
        wrap_up_started_ms = now_ms

    if wrap_up_started_ms and ticks_diff(now_ms, wrap_up_started_ms) >= _FLUSH_DRAIN_MS:
        mqtt.disconnect()
        print("DEMO_COMPLETE")
        break

    if ticks_diff(now_ms, overall_deadline_ms) >= 0:
        print(
            f"STATUS: FAIL_DEMO_DEADLINE "
            f"telemetry_sent={telemetry_sent} "
            f"command_received={command_received}",
        )
        raise SystemExit(1)

    runner.wait(now_ms)
