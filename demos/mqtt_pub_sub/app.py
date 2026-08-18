"""Publish and receive MQTT messages from a board, both directions.

This is the file that runs on the board.  It waits for wifi, connects to
an MQTT broker on your laptop, announces that it is online, subscribes to
a command topic, publishes three readings, and reacts to one command sent
back to it.

MQTT is a small publish/subscribe protocol: everyone connects to a
broker, publishes to named topics, and subscribes to the topics they care
about.  Nobody connects to anybody else directly.

Three habits worth stealing from this file:

* **Publish whenever you like.**  ``publish()`` before the broker session
  is up does not fail; the client buffers it and sends it once connected.
  There is no "am I connected yet" check anywhere below.
* **Say goodbye in advance.**  ``set_will(...)`` hands the broker a
  message to publish on this board's behalf if the board drops off
  without a proper goodbye.  That plus the ``online`` publish on connect
  is how anything watching knows whether the board is there.
* **Do the connect-time setup in ``on_connect``.**  It fires once the
  broker session is up, which is the first moment a subscription can go
  on the wire.

What you will see::

    WIFI_OK ip=10.0.0.42
    MQTT_CONNECTED broker=10.0.0.5:1883 client_id=chumicro-mqtt-demo-board
    RETAINED_STATE_SENT topic=demo/chumicro-mqtt-demo-board/state
    SUBSCRIBED topic=demo/chumicro-mqtt-demo-board/cmd
    TELEMETRY_SENT seq=1
    TELEMETRY_SENT seq=2
    CMD_RECEIVED topic=demo/chumicro-mqtt-demo-board/cmd payload_hex=626c696e6b
      text: blink
    TELEMETRY_SENT seq=3
    DEMO_COMPLETE

Nothing stops after that.  The loop goes on turning, the way a board
program does, and the script on your laptop closes the connection once
it has seen what it came for.

The UPPERCASE lines are for the script running on your laptop, which
reads them to follow how far the board got.  They are ordinary ``print``
calls: the format is just ``NAME key=value``, and the values have to be
free of spaces and ``=`` signs so the laptop side can split them apart.
That is why the command payload rides as hex, with the readable version
on the indented line under it.
"""

import json

from chumicro_config import load_runtime_config
from chumicro_mqtt import MQTTClient
from chumicro_runner import Runner
from chumicro_timing import ticks_diff, ticks_ms
from chumicro_wifi import WifiConfig, WifiService, WifiState

TELEMETRY_COUNT = 3
TELEMETRY_INTERVAL_MS = 1_500

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
    print(f"MQTT_CONNECTED broker={broker} client_id={client_id}")
    mqtt.publish(state_topic, b"online", qos=1, retain=True)
    print(f"RETAINED_STATE_SENT topic={state_topic}")
    mqtt.subscribe(command_topic, qos=1)


def on_subscribe(topic, granted_qos):
    """SUBACK arrived: the subscription is live at the broker.

    The marker fires here, not at the subscribe() call.  The host
    driver gates its command publish on SUBSCRIBED, and a marker
    printed at enqueue time races the broker (a command published
    before the broker processes the SUBSCRIBE is dropped unseen).
    """
    print(f"SUBSCRIBED topic={topic}")


def on_command_message(topic, payload):
    global command_received
    text = (
        payload.decode("utf-8", "replace") if isinstance(payload, bytes)
        else payload
    )
    command_received = True
    print(f"CMD_RECEIVED topic={topic} payload_hex={text.encode().hex()}")
    print(f"  text: {text}")
    announce_if_done()


def announce_if_done():
    """Say so once both halves have happened.  Either one can be last."""
    if telemetry_sent >= TELEMETRY_COUNT and command_received:
        print("DEMO_COMPLETE")


def on_wifi_state(_old, new):
    if new == WifiState.CONNECTED:
        print(f"WIFI_OK ip={wifi.ip}")
        mqtt.connect()  # link is back: reconnect now (also clears the hold)
    else:
        # WifiService reports link loss as RECONNECTING / FAILED, so any
        # state but CONNECTED means: stop dialing a dead radio.
        mqtt.hold()


def publish_telemetry(now_ms):
    """Publish one QoS 1 telemetry sample per call until the quota is met.

    No CONNECTED guard: a sample produced before the broker session is
    up buffers in the client's pre-connect queue and flushes on CONNACK.
    """
    global telemetry_sent
    if telemetry_sent >= TELEMETRY_COUNT:
        return
    telemetry_sent += 1
    payload = json.dumps({
        "seq": telemetry_sent,
        "value": 20 + telemetry_sent,
        "uptime_ms": ticks_diff(now_ms, start_ms),
    }).encode()
    mqtt.publish(telemetry_topic, payload, qos=1)
    print(f"TELEMETRY_SENT seq={telemetry_sent}")
    announce_if_done()


mqtt.on_connect = on_connect
mqtt.on_subscribe = on_subscribe
mqtt.on_message = on_command_message
wifi.on_state_change(on_wifi_state)

def report_fault(entry, error):
    """Runs if a service raises.  The loop keeps going; this says so."""
    print(f"SERVICE_FAULT service={type(entry.service).__name__} "
          f"error={type(error).__name__}")
    print(f"  detail: {error!r}")


runner = Runner(on_handler_error=report_fault)
runner.add(wifi)
runner.add(mqtt)
runner.add_periodic(publish_telemetry, period_ms=TELEMETRY_INTERVAL_MS)

# The main loop.  tick() gives every registered service one small step,
# and wait() then parks the CPU until the next event or timer deadline.
# It never ends, which is what a board program does.  Your own project's
# loop looks exactly like this one.
while True:
    now_ms = runner.tick()
    runner.wait(now_ms)
