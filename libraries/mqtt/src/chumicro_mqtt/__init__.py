"""Non-blocking MQTT 3.1.1 client for CircuitPython, MicroPython, and CPython.

Built on :mod:`chumicro_sockets` (TCP + TLS) and :mod:`chumicro_timing`
(ticks).  No async, no threads — a tick-based runner contract:
:meth:`MQTTClient.check(now_ms) -> bool` reports whether work is
pending; :meth:`handle(now_ms)` does one tick of progress.

Public API::

    from chumicro_mqtt import MQTTClient, WhenOversized
    from chumicro_mqtt.sockets_factory import chumicro_sockets_factory

    factory = chumicro_sockets_factory(
        {"mqtt.broker.host": "broker.example.com", "mqtt.broker.port": 1883},
        radio=wifi_radio,
    )
    client = MQTTClient(socket_factory=factory, client_id="my-thing")

    client.on_message = lambda topic, payload: print(topic, payload)
    client.connect()
    while True:
        if client.check(now_ms()):
            client.handle(now_ms())

QoS 0 + QoS 1 are implemented; QoS 2 raises :class:`UnsupportedQoSError`.

Source layout:

* :mod:`chumicro_mqtt._wire` — wire-format primitives, packet
  encoders/decoder, and protocol exceptions.
* :mod:`chumicro_mqtt.client` — :class:`MQTTClient` plus its connection-
  lifecycle classes (``Awaiting``, ``InFlightPublish``, ``InFlightTable``,
  ``PendingResponse``) — internal to the orchestration; reach into the
  submodule directly if you need them.
* :mod:`chumicro_mqtt.sockets_factory` — opt-in
  :func:`chumicro_sockets_factory` convenience helper that wires the
  default :mod:`chumicro_sockets` transport.  Lives in its own
  submodule so users with a custom ``socket_factory`` never trigger
  the :mod:`chumicro_sockets` deploy.
* :mod:`chumicro_mqtt.testing` — host-only fakes (excluded from device
  bundle).
"""

from chumicro_mqtt._wire import (
    MQTTBackpressureError,
    MQTTConnectError,
    MQTTError,
    MQTTProtocolError,
    UnsupportedQoSError,
    decode_varlen,
    encode_connect,
    encode_puback,
    encode_publish,
    encode_string,
    encode_subscribe,
    encode_unsubscribe,
    encode_varlen,
    topic_matches,
)
from chumicro_mqtt.client import MQTTClient, ProtocolState, WhenOversized

__all__ = [
    "MQTTClient",
    "MQTTBackpressureError",
    "MQTTConnectError",
    "MQTTError",
    "MQTTProtocolError",
    "ProtocolState",
    "UnsupportedQoSError",
    "WhenOversized",
    "decode_varlen",
    "encode_connect",
    "encode_puback",
    "encode_publish",
    "encode_string",
    "encode_subscribe",
    "encode_unsubscribe",
    "encode_varlen",
    "topic_matches",
]
