"""``chumicro_mqtt`` connects a board to an MQTT broker and moves messages one non-blocking step at a time.

MQTT (version 3.1.1 here) is a publish/subscribe protocol.  Every device
connects to one server, the broker.  A device publishes a message to a named
topic, such as ``"home/kitchen/temp"``, and the broker passes the message to
every device subscribed to that topic.  Each message carries a QoS (quality
of service) level.  QoS 0 delivers a message at most once.  QoS 1 delivers
it at least once.  A retained message stays on the broker, which hands it
to each later subscriber of its topic.  A last will is a message the broker
publishes for a device that drops off without a clean disconnect.
``MQTTClient`` holds one connection to a broker.
"""

import gc

from chumicro_mqtt._wire import (
    MQTTBackpressureError,
    MQTTConnectError,
    MQTTError,
    MQTTProtocolError,
    UnsupportedQoSError,
    topic_matches,
)

gc.collect()


def __getattr__(name):
    if name in (
        "InboundPublish",
        "MQTTClient",
        "ProtocolState",
        "WhenOversized",
        "default_client_id",
    ):
        # Lazy-import the largest module so boards that never build a client
        # pay no RAM; collect first so it compiles into a swept heap.
        gc.collect()
        import chumicro_mqtt.client as _client  # noqa: PLC0415

        return getattr(_client, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    # pyright: ignore[reportUnsupportedDunderAll]: InboundPublish, MQTTClient,
    # ProtocolState, WhenOversized, and default_client_id are PEP-562 lazy via
    # __getattr__.
    "InboundPublish",
    "MQTTClient",
    "MQTTBackpressureError",
    "MQTTConnectError",
    "MQTTError",
    "MQTTProtocolError",
    "ProtocolState",
    "UnsupportedQoSError",
    "WhenOversized",
    "default_client_id",
    "topic_matches",
]

gc.collect()
