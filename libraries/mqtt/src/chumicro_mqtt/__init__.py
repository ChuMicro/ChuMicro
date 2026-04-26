"""Non-blocking MQTT 3.1.1 client for CircuitPython, MicroPython, and CPython.

Built on :mod:`chumicro_sockets` (TCP + TLS) and :mod:`chumicro_timing`
(ticks).  No async, no threads — Decision 0014's runner pattern:
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

QoS 0 + QoS 1 are implemented; QoS 2 raises
:class:`UnsupportedQoSError` (Decision 0029 Phase 6 — the wire-level
constants are reserved for forward-compat but the handlers aren't
wired).

Decision 0029 Phase 6 catalogues the rewrite of the pythonProject3
client this library replaces: per-packet-id in-flight tracking,
explicit state machine, no broad ``_waiting_state`` lock, structured
oversized-message policy, no ``adafruit_connection_manager``
dependency.
"""

from chumicro_mqtt._encoder import (
    encode_connect,
    encode_puback,
    encode_publish,
    encode_subscribe,
    encode_unsubscribe,
)
from chumicro_mqtt._errors import (
    MQTTConnectError,
    MQTTError,
    MQTTProtocolError,
    UnsupportedQoSError,
)
from chumicro_mqtt._packets import (
    PACKET_CONNACK,
    PACKET_CONNECT,
    PACKET_PINGREQ,
    PACKET_PINGRESP,
    PACKET_PUBACK,
    PACKET_PUBLISH,
    PACKET_SUBACK,
    PACKET_SUBSCRIBE,
    PACKET_UNSUBACK,
    PACKET_UNSUBSCRIBE,
    decode_varlen,
    encode_string,
    encode_varlen,
    topic_matches,
)
from chumicro_mqtt._state import (
    Awaiting,
    InFlightPublish,
    InFlightTable,
    PendingResponse,
    ProtocolState,
)
from chumicro_mqtt.client import MQTTClient, WhenOversized

__all__ = [
    "Awaiting",
    "InFlightPublish",
    "InFlightTable",
    "MQTTClient",
    "MQTTConnectError",
    "MQTTError",
    "MQTTProtocolError",
    "PACKET_CONNACK",
    "PACKET_CONNECT",
    "PACKET_PINGREQ",
    "PACKET_PINGRESP",
    "PACKET_PUBACK",
    "PACKET_PUBLISH",
    "PACKET_SUBACK",
    "PACKET_SUBSCRIBE",
    "PACKET_UNSUBACK",
    "PACKET_UNSUBSCRIBE",
    "PendingResponse",
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
