"""Print every MQTT message sent to the board, one at a time, forever.

The board joins your wifi, connects to an MQTT broker, subscribes to
the topic ``chumicro-demo/cmd``, and prints each message that arrives
there until you unplug it.

MQTT is a publish/subscribe protocol.  The board and your laptop each
connect to a broker, a small server that passes messages along.  Your
laptop publishes to a named topic, and every client subscribed to that
topic, the board included, gets a copy.

The receiving code in ``print_commands()`` reads top to bottom: wait
for the next message, print it, wait again.  It is a generator (a
function with ``yield`` in it), and ``yield from mqtt.next_message()``
pauses it until a message arrives.  While it is paused, the runner at
the bottom of the file keeps the connection and everything else on the
board moving.  ``telemetry.py`` receives through an ``on_message``
callback instead.  A client uses one or the other: the first
``next_message()`` call switches ``on_message`` off.

Stop the broker while this runs and the board prints that it lost the
connection.  Start it again and the board reconnects on its own and
subscribes again, so the next message you send still arrives.

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

4. Once the board says ``MQTT connected``, send it messages from a
   second terminal::

       mosquitto_pub -h localhost -t chumicro-demo/cmd -m ping
       mosquitto_pub -h localhost -t chumicro-demo/cmd -m blink

Run it on the board
===================

Set ``WIFI_SSID``, ``WIFI_PASSWORD``, and ``BROKER_HOST`` below.
``BROKER_HOST`` is your laptop's IP address on the wifi network:
``ipconfig getifaddr en0`` prints it on a Mac, ``hostname -I`` on
Linux.  When you deploy with ``chumicro-workspace``, the values under
``[wifi]`` and ``[mqtt.broker]`` in your ``secrets.toml`` are used
instead::

    chumicro-workspace deploy-example mqtt receive_stream --device <id>

What you will see
=================

::

    WIFI_OK ip=10.0.0.42
    Connecting to MQTT broker 10.0.0.5:1883
    MQTT connected
    [1] chumicro-demo/cmd: b'ping'
    [2] chumicro-demo/cmd: b'blink'

Try sending ``on`` and ``off`` and switching an LED in
``print_commands()``.
"""

# Runs on CircuitPython and MicroPython boards.  helpers.wifi_up picks
# the right wifi calls for each.
__chumicro_runtimes__ = ("circuitpython", "micropython")

from chumicro_mqtt import MQTTClient
from chumicro_runner import Runner
from helpers import runtime_config, wifi_up

WIFI_SSID = "your-wifi-ssid"  # noqa: S105 - replace before deploying
WIFI_PASSWORD = "your-wifi-password"  # noqa: S105 - replace before deploying
BROKER_HOST = ""  # your laptop's IP address, for example "192.168.1.20"
BROKER_PORT = 1883
COMMAND_TOPIC = "chumicro-demo/cmd"

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
    # Runs when a working connection drops.  The client reconnects on
    # its own: at once, then 1, 2, 4... seconds apart, at most a minute.
    print(f"MQTT connection lost: {mqtt.last_error}")


mqtt.on_connect = on_connect
mqtt.on_disconnect = on_disconnect

# Ask the broker for COMMAND_TOPIC.  The client sends the request once
# connected, and again after every reconnect.
mqtt.subscribe(COMMAND_TOPIC, qos=1)
mqtt.connect()


def print_commands():
    count = 0
    while True:
        # Pause here until a message arrives.
        message = yield from mqtt.next_message()
        if message is None:
            # The client gave up for good, for example because the
            # broker refused its username or password.
            print(f"MQTT stopped: {mqtt.last_error}")
            return
        count += 1
        print(f"[{count}] {message.topic}: {message.payload}")


# The runner takes turns between everything added to it: the client's
# network work and the print_commands() generator.
runner = Runner()
runner.add(mqtt)
runner.add_generator(print_commands())

while True:
    now_ms = runner.tick()   # each added task takes one small step
    runner.wait(now_ms)      # then the CPU rests until a message or timer is due
