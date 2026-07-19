"""Board-side of the mqtt_pub_sub demo.

Wires ``chumicro_wifi.WifiService`` + ``chumicro_mqtt.MQTTClient`` into
one ``chumicro_runner.Runner`` and drives them with
``while True: now = runner.tick(); runner.wait(now)``.

Reads like a mainstream MQTT quickstart (paho / Adafruit MiniMQTT): set
a Last Will, set the callbacks once, connect, let the loop run.  The
periodic publisher just calls ``publish``.  A publish issued before the
broker session is up buffers in the client's pre-connect queue and
flushes on CONNACK (``when_disconnected="queue"``, the default), so no
state guard is needed.  Connect-time setup (publish presence, subscribe
to commands) happens in ``on_connect``, fire-and-forget, with no
callback chain and no waiting on QoS 1 acks (the client tracks PUBACK /
SUBACK internally; the app never needs to).

Presence pair: a retained ``"offline"`` Last Will the broker publishes
if this board drops uncleanly, plus the retained ``"online"`` published
on connect.  Then the demo publishes three QoS 1 telemetry samples on a
1.5 s cadence, and prints ``DEMO_COMPLETE`` once all three are sent and
the host's one command has arrived.

Marker lines (``WIFI_OK``, ``MQTT_CONNECTED``, ``RETAINED_STATE_SENT``,
``SUBSCRIBED``, ``TELEMETRY_SENT``, ``CMD_RECEIVED``,
``DEMO_COMPLETE``) drive the host driver via stdout markers.
"""

import json

from chumicro_config import load_runtime_config
from chumicro_mqtt import MQTTClient
from chumicro_runner import Runner
from chumicro_test_harness.markers import marker
from chumicro_timing import ticks_diff, ticks_ms
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
mqtt.set_will(state_topic, b"offline", qos=1, retain=True)

# Demo progress at module scope so the callbacks can read and write
# without ceremony.  Small enough that a class would add noise.
telemetry_sent = 0
command_received = False
start_ms = ticks_ms()


def on_connect():
    """Connect-time setup, fired once: publish presence, subscribe to commands."""
    marker("MQTT_CONNECTED", broker=broker, client_id=client_id)
    mqtt.publish(state_topic, b"online", qos=1, retain=True)
    marker("RETAINED_STATE_SENT", topic=state_topic)
    mqtt.subscribe(command_topic, qos=1)


def on_subscribe(topic, granted_qos):
    """SUBACK arrived: the subscription is live at the broker.

    The marker fires here, not at the subscribe() call.  The host
    driver gates its command publish on SUBSCRIBED, and a marker
    printed at enqueue time races the broker (a command published
    before the broker processes the SUBSCRIBE is dropped unseen).
    """
    marker("SUBSCRIBED", topic=topic)


def on_command_message(topic, payload):
    global command_received
    text = (
        payload.decode("utf-8", "replace") if isinstance(payload, bytes)
        else payload
    )
    command_received = True
    marker("CMD_RECEIVED", topic=topic, payload_hex=text.encode())
    print(f"  text: {text}")


def on_wifi_state(_old, new):
    if new == WifiState.CONNECTED:
        marker("WIFI_OK", ip=wifi.ip)
        mqtt.connect()


def publish_telemetry(now_ms):
    """Publish one QoS 1 telemetry sample per call until the quota is met.

    No CONNECTED guard: a sample produced before the broker session is
    up buffers in the client's pre-connect queue and flushes on CONNACK.
    """
    global telemetry_sent
    if telemetry_sent >= _TELEMETRY_COUNT:
        return
    telemetry_sent += 1
    payload = json.dumps({
        "seq": telemetry_sent,
        "value": 20 + telemetry_sent,
        "uptime_ms": ticks_diff(now_ms, start_ms),
    }).encode()
    mqtt.publish(telemetry_topic, payload, qos=1)
    marker("TELEMETRY_SENT", seq=telemetry_sent)


mqtt.on_connect = on_connect
mqtt.on_subscribe = on_subscribe
mqtt.on_message = on_command_message
wifi.on_state_change(on_wifi_state)

runner = Runner(on_handler_error=lambda entry, error: print("SERVICE_FAULT", entry.service, repr(error)))
runner.add(wifi)
runner.add(mqtt)
runner.add_periodic(publish_telemetry, period_ms=_TELEMETRY_INTERVAL_MS)

if not runner.run_until(
    lambda: telemetry_sent >= _TELEMETRY_COUNT and command_received,
    timeout_ms=_DEMO_DEADLINE_MS,
):
    print(
        f"STATUS: FAIL_DEMO_DEADLINE "
        f"telemetry_sent={telemetry_sent} "
        f"command_received={command_received}",
    )
    raise SystemExit(1)

# Drain window: keep ticking so the broker's QoS-1 acks land before
# the disconnect tears the socket down.
runner.run_until(timeout_ms=_FLUSH_DRAIN_MS)
mqtt.disconnect()
marker("DEMO_COMPLETE")
