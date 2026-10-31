"""Send and receive MQTT messages on a board, every two seconds, forever.

This is the file that runs on the board.  It waits for wifi, connects to
an MQTT broker running on your laptop, announces that it is online, and
listens for commands.  Every two seconds it publishes a message with how
long it has been running, and it prints every command the laptop sends
back.

MQTT is a small publish/subscribe protocol.  Everyone connects to one
broker, publishes messages to named topics, and subscribes to the topics
they care about.  Nobody connects to anybody else directly.

Two habits worth copying from this file:

* **Leave a goodbye with the broker.**  ``set_will(...)`` hands the
  broker a message to publish for this board if the board drops off
  without a proper goodbye.  Together with the ``online`` published on
  connect, anything watching the state topic can tell whether the board
  is there.
* **Do connect-time setup in ``on_connect``.**  It runs each time the
  broker session comes up, which is the first moment a subscription can
  go on the wire.

What the board prints::

      waiting for the broker...
    WIFI_OK ip=10.0.0.42
    MQTT_CONNECTED broker=10.0.0.5:1883 client_id=chumicro-mqtt-demo-board
    RETAINED_STATE_SENT topic=demo/chumicro-mqtt-demo-board/state
    SUBSCRIBED topic=demo/chumicro-mqtt-demo-board/cmd
    CMD_RECEIVED topic=demo/chumicro-mqtt-demo-board/cmd payload_hex=70696e67
      text: ping
    DEMO_COMPLETE
      sent message 1: {"seq": 1, "uptime_ms": 9412}
      sent message 2: {"seq": 2, "uptime_ms": 11412}
      sent message 3: {"seq": 3, "uptime_ms": 13412}

The UPPERCASE lines are for the script on your laptop, which reads them
to follow how far the board got.  They are ordinary ``print`` calls in a
``NAME key=value`` shape, and a value may not contain a space or an
``=``.  That is why the command rides as hex, with the readable text on
the indented line under it.  The indented lines are for you.

Try it: change ``PUBLISH_EVERY_MS`` and run the demo again, or add a
second topic that reports something real, such as a button state.
"""

import json

from chumicro_config import load_runtime_config
from chumicro_mqtt import MQTTClient, ProtocolState
from chumicro_runner import Runner
from chumicro_timing import ticks_diff, ticks_ms
from chumicro_wifi import WifiConfig, WifiService, WifiState

PUBLISH_EVERY_MS = 2_000

config = load_runtime_config()
client_id = config.get("mqtt.client_id", "chumicro-mqtt-demo-board")
broker = f"{config['mqtt.broker.host']}:{config['mqtt.broker.port']}"
state_topic = f"demo/{client_id}/state"
command_topic = f"demo/{client_id}/cmd"
telemetry_topic = f"demo/{client_id}/telemetry"

wifi = WifiService(WifiConfig.from_config(config))
mqtt = MQTTClient.from_config(config, radio=wifi.adapter.radio)

# If this board drops off without a goodbye, the broker publishes this
# retained "offline" for it.  on_connect publishes the matching "online".
mqtt.set_will(state_topic, b"offline", qos=1, retain=True)

start_ms = ticks_ms()
messages_sent = 0
commands_received = 0


def on_connect():
    """Runs each time the broker session comes up: say hello, then subscribe."""
    print(f"MQTT_CONNECTED broker={broker} client_id={client_id}")
    mqtt.publish(state_topic, b"online", qos=1, retain=True)
    print(f"RETAINED_STATE_SENT topic={state_topic}")
    mqtt.subscribe(command_topic, qos=1)


def on_subscribe(topic, _granted_qos):
    """Runs when the broker confirms the subscription.

    Commands sent before this point would not reach the board, so the
    laptop script waits for ``SUBSCRIBED`` before it sends one.
    """
    print(f"SUBSCRIBED topic={topic}")


def on_command(topic, payload):
    """Runs for every message that arrives on the command topic."""
    global commands_received
    commands_received += 1
    print(f"CMD_RECEIVED topic={topic} payload_hex={payload.hex()}")
    print(f"  text: {payload.decode('utf-8', 'replace')}")
    if commands_received == 1:
        print("DEMO_COMPLETE")


def publish_uptime(now_ms):
    """Runs every two seconds: publish one message while the broker is connected."""
    global messages_sent
    if mqtt.state != ProtocolState.CONNECTED:
        print("  waiting for the broker...")
        return
    messages_sent += 1
    payload = json.dumps({
        "seq": messages_sent,
        "uptime_ms": ticks_diff(now_ms, start_ms),
    })
    mqtt.publish(telemetry_topic, payload, qos=1)
    print(f"  sent message {messages_sent}: {payload}")


def on_wifi_state(_old, new):
    """Connect to the broker whenever wifi comes up; stop dialing while it is down."""
    if new == WifiState.CONNECTED:
        print(f"WIFI_OK ip={wifi.ip}")
        mqtt.connect()
    else:
        mqtt.hold()


def report_fault(entry, error):
    """Runs if a service raises.  The loop keeps going; this says so."""
    print(f"SERVICE_FAULT service={type(entry.service).__name__} "
          f"error={type(error).__name__}")
    print(f"  detail: {error!r}")


mqtt.on_connect = on_connect
mqtt.on_subscribe = on_subscribe
mqtt.on_message = on_command
wifi.on_state_change(on_wifi_state)

runner = Runner(on_handler_error=report_fault)
runner.add(wifi)
runner.add(mqtt)
runner.add_periodic(publish_uptime, period_ms=PUBLISH_EVERY_MS)

# The main loop.  tick() gives every registered service one small step,
# and wait() then parks the CPU until the next event or timer deadline.
# It never ends, which is what a board program does.
while True:
    now_ms = runner.tick()
    runner.wait(now_ms)
