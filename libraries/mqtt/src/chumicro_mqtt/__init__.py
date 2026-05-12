"""Non-blocking MQTT 3.1.1 client for CircuitPython, MicroPython, and CPython.

Built on :mod:`chumicro_sockets` (TCP + TLS) and :mod:`chumicro_timing`
(ticks).  No async, no threads — a tick-based runner contract:
:meth:`MQTTClient.check(now_ms) -> bool` reports whether work is
pending; :meth:`handle(now_ms)` does one tick of progress.

Public API::

    from chumicro_sockets import tcp_client_socket
    from chumicro_mqtt import MQTTClient, WhenOversized

    sock = tcp_client_socket("broker.example.com", 1883, radio=wifi_radio)
    client = MQTTClient(sock, client_id="my-thing")

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
