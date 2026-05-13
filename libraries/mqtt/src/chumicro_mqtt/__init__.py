"""Non-blocking MQTT 3.1.1 client for CircuitPython, MicroPython, and CPython.

Built on :mod:`chumicro_sockets` (TCP + TLS) and :mod:`chumicro_timing`
(ticks).  Tick-based runner contract — :meth:`MQTTClient.check(now_ms)`
reports whether work is pending and :meth:`handle(now_ms)` does one
slice of progress per call.

QoS 0 + QoS 1 supported; QoS 2 raises :class:`UnsupportedQoSError`.
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
from chumicro_mqtt.client import MQTTClient, MQTTPublisher, ProtocolState, WhenOversized

__all__ = [
    "MQTTClient",
    "MQTTPublisher",
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
