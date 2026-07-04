"""MQTT receive-stream client via next_message on a real board.

Brings wifi up via the local ``helpers`` module, connects to a
configured MQTT broker, subscribes to one command topic, then receives
every inbound message with a ``yield from mqtt.next_message()`` loop
driven by ``Runner.add_generator`` — wait for a message, act on it,
wait for the next.

Pair with ``telemetry.py``, which uses the ``on_message`` callback and
pattern handlers for multi-topic fan-out; this one shows the linear
receive loop for a single-subscription consumer — the session and the
consumer are both registered with the runner.  Pick one inbound
surface per client, not both: the first ``next_message()`` call
switches data delivery from the callbacks to the stream.

Configuration
=============

Reads the deployed ``runtime_config.msgpack`` via the flat-key API:

* WiFi (read by ``helpers.wifi_up``): ``wifi.ssid`` / ``wifi.password``.
* MQTT (read by ``MQTTClient.from_config``): ``mqtt.broker.host`` /
  ``mqtt.broker.port`` / ``mqtt.client_id``.
* App-level: ``mqtt.command_topic`` — the topic this consumer drains
  (defaults to ``chumicro-demo/cmd``).

Deploying
=========

Deploy with ``chumicro-workspace``::

    chumicro-workspace deploy-example mqtt receive_stream --device <id>

Example output::

    WIFI_OK ip=10.0.0.42
    [mqtt] connected
    [rx 1] chumicro-demo/cmd <- b'ping'
    [rx 2] chumicro-demo/cmd <- b'blink'
"""

#: Cross-runtime: wifi-up via :mod:`helpers` dispatches per
#: ``sys.implementation.name`` (CP / MP) and the MQTT client is
#: pure-Python.  The marker tells :func:`scripts.verify_examples`
#: + ``deploy-example`` to allow this file on either runtime.
__chumicro_runtimes__ = ("circuitpython", "micropython")

from chumicro_mqtt import MQTTClient
from chumicro_runner import Runner
from helpers import runtime_config, wifi_up

WIFI_SSID = "your-wifi-ssid"  # noqa: S105 - replace before deploying
WIFI_PASSWORD = "your-wifi-password"  # noqa: S105 - replace before deploying

config = runtime_config()

radio, ip = wifi_up(WIFI_SSID, WIFI_PASSWORD)
print(f"WIFI_OK ip={ip}")

mqtt = MQTTClient.from_config(config, radio=radio)
command_topic = config.get("mqtt.command_topic", "chumicro-demo/cmd")


def on_connect():
    # subscribe() requires the CONNECTED state, so wire it through
    # on_connect (it fires once the broker session is up).
    print("[mqtt] connected")
    mqtt.subscribe(command_topic, qos=1)


mqtt.on_connect = on_connect
mqtt.connect()


def consume_commands():
    received = 0
    while True:
        message = yield from mqtt.next_message()
        if message is None:
            break
        received += 1
        print(f"[rx {received}] {message.topic} <- {message.payload!r}")
    print(f"[mqtt] stream ended after {received} message(s)")


runner = Runner()
runner.add(mqtt)
handle = runner.add_generator(consume_commands())
runner.run_until(handle)
