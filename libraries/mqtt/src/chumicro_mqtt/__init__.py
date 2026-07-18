"""Non-blocking MQTT 3.1.1 client for CircuitPython, MicroPython, and CPython."""

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
    # pyright: ignore[reportUnsupportedDunderAll]: InboundPublish,
    # MQTTClient, ProtocolState, and WhenOversized are PEP-562 lazy via
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
