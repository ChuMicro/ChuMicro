"""Publish a temperature reading over MQTT every five seconds, forever.

The board joins your wifi, connects to an MQTT broker, and publishes a
reading to the topic ``chumicro-demo/telemetry`` every five seconds
until you unplug it.  It also subscribes to ``chumicro-demo/cmd`` and
prints every message sent there.

MQTT is a publish/subscribe protocol.  The board and your laptop each
connect to a broker, a small server that passes messages along.  The
board publishes to a named topic, and every client subscribed to that
topic gets a copy.

Readings go out at QoS 1 ("quality of service" level 1): the broker
confirms each one, and the client sends it again until it does.  The
``sent`` lines print when that confirmation arrives.

Stop the broker while this runs.  The board prints that it lost the
connection and holds each new reading.  Start the broker again and the
board reconnects on its own and sends what it held.  Nothing in this
file reconnects by hand; ``mqtt.handle()`` does it.

If you have used ``adafruit_minimqtt``, ``mqtt.handle(now_ms)`` plays
the part of ``loop()``, and returns as soon as it has done one small
step of network work, so the rest of your loop never waits on it.

Run a broker on your laptop
===========================

1. Install Mosquitto: ``brew install mosquitto`` on a Mac, or
   ``sudo apt install mosquitto mosquitto-clients`` on Debian or
   Ubuntu.  On Linux the package starts a broker that only answers the
   laptop itself; stop it with ``sudo systemctl stop mosquitto``.
2. Save these two lines as ``mosquitto.conf``.  They let clients on
   your wifi connect without a password::

       listener 1883
       allow_anonymous true

3. Start the broker and leave it running.  ``-v`` prints every
   connection and message::

       mosquitto -c mosquitto.conf -v

4. In a second terminal, watch everything under ``chumicro-demo/``::

       mosquitto_sub -h localhost -t 'chumicro-demo/#' -v

5. To send the board a command, run this from a third terminal::

       mosquitto_pub -h localhost -t chumicro-demo/cmd -m ping

Run it on the board
===================

Set ``WIFI_SSID``, ``WIFI_PASSWORD``, and ``BROKER_HOST`` below.
``BROKER_HOST`` is your laptop's IP address on the wifi network:
``ipconfig getifaddr en0`` prints it on a Mac, ``hostname -I`` on
Linux.  When you deploy with ``chumicro-workspace``, the values under
``[wifi]`` and ``[mqtt.broker]`` in your ``secrets.toml`` are used
instead::

    chumicro-workspace deploy-example mqtt telemetry --device <id>

What you will see
=================

::

    WIFI_OK ip=10.0.0.42
    Connecting to MQTT broker 10.0.0.5:1883
    MQTT connected
    sent chumicro-demo/telemetry 21.2
    sent chumicro-demo/telemetry 21.6
    command on chumicro-demo/cmd: b'ping'
    sent chumicro-demo/telemetry 22.0
    MQTT connection lost: broker closed connection
    holding 22.4 until the broker is back (connector failed: [Errno 104] ECONNRESET)
    holding 22.8 until the broker is back (connector failed: [Errno 104] ECONNRESET)
    MQTT connected
    sent chumicro-demo/telemetry 22.4
    sent chumicro-demo/telemetry 22.8
    sent chumicro-demo/telemetry 23.1

The text in parentheses is why the last reconnect attempt failed, and
its wording depends on the board.  The client holds up to eight
readings while the broker is away.  A longer outage prints ``dropped``
for each reading that does not fit.

Try swapping ``read_temperature()`` for a real sensor, or making
``on_message`` switch an LED when ``on`` or ``off`` arrives.
"""

# Runs on CircuitPython and MicroPython boards.  helpers.wifi_up picks
# the right wifi calls for each.
__chumicro_runtimes__ = ("circuitpython", "micropython")

import math

from chumicro_mqtt import MQTTBackpressureError, MQTTClient, ProtocolState
from chumicro_timing import Rate, ticks_ms
from helpers import runtime_config, wifi_up

WIFI_SSID = "your-wifi-ssid"  # noqa: S105 - replace before deploying
WIFI_PASSWORD = "your-wifi-password"  # noqa: S105 - replace before deploying
BROKER_HOST = ""  # your laptop's IP address, for example "192.168.1.20"
BROKER_PORT = 1883
TOPIC = "chumicro-demo/telemetry"
COMMAND_TOPIC = "chumicro-demo/cmd"
PUBLISH_EVERY_S = 5

# Join wifi.  wifi_up waits until the board has an IP address.
radio, ip = wifi_up(WIFI_SSID, WIFI_PASSWORD)
print(f"WIFI_OK ip={ip}")

# Settings deployed by chumicro-workspace win over the constants above.
# A file copied to the board by hand gets an empty config here.
config = runtime_config()
config.setdefault("mqtt.broker.host", BROKER_HOST)
config.setdefault("mqtt.broker.port", BROKER_PORT)
if not config["mqtt.broker.host"]:
    raise RuntimeError("set BROKER_HOST at the top of this file to your broker's IP address")
print(f"Connecting to MQTT broker {config['mqtt.broker.host']}:{config['mqtt.broker.port']}")

# from_config builds a client that dials the broker through this board's
# wifi radio, and dials again by itself whenever the connection drops.
mqtt = MQTTClient.from_config(config, radio=radio)


def on_connect():
    # Runs each time the broker accepts the board, reconnects included.
    print("MQTT connected")


def on_disconnect():
    # Runs when a working connection drops.  handle() then reconnects on
    # its own: at once, then 1, 2, 4... seconds apart, at most a minute.
    print(f"MQTT connection lost: {mqtt.last_error}")


def on_publish(topic, payload):
    # Runs when the broker confirms it received a QoS 1 message.
    print(f"sent {topic} {payload.decode()}")


def on_message(topic, payload):
    # Runs for every message that arrives on a subscribed topic.
    print(f"command on {topic}: {payload}")


mqtt.on_connect = on_connect
mqtt.on_disconnect = on_disconnect
mqtt.on_publish = on_publish
mqtt.on_message = on_message

# Ask the broker for COMMAND_TOPIC.  The client sends the request once
# connected, and again after every reconnect.
mqtt.subscribe(COMMAND_TOPIC, qos=1)
mqtt.connect()


def read_temperature():
    # A stand-in for a real sensor: drifts slowly between 15 and 25.
    return 20 + 5 * math.sin(ticks_ms() / 20_000)


def publish_reading():
    reading = f"{read_temperature():.1f}"
    try:
        # publish() never waits.  While the broker is unreachable, the
        # client holds the reading and sends it after reconnecting.
        mqtt.publish(TOPIC, reading, qos=1)
    except MQTTBackpressureError:
        print(f"dropped {reading}: eight readings already wait for the broker")
        return
    if mqtt.state != ProtocolState.CONNECTED:
        reason = mqtt.last_error or "still connecting"
        print(f"holding {reading} until the broker is back ({reason})")


publish_timer = Rate(PUBLISH_EVERY_S * 1000, ticks_ms())

while True:
    now_ms = ticks_ms()

    # check() is True while the client has work to do.  handle() takes
    # one small step of it (connect, send, read what has arrived, keep
    # the connection alive, or reconnect) and returns without waiting.
    if mqtt.check(now_ms):
        mqtt.handle(now_ms)

    # Every PUBLISH_EVERY_S seconds, publish a reading.
    if publish_timer.due(now_ms):
        publish_reading()

    # Anything else you add here, such as blinking an LED or reading a
    # button, runs on every pass, even while the broker is away.
