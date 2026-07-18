"""Non-blocking MQTT 3.1.1 client for CircuitPython, MicroPython, and CPython.

Drive :class:`MQTTClient` from a tick loop: :meth:`MQTTClient.check`
reports whether work is pending and :meth:`MQTTClient.handle` does one
slice of progress per call. QoS 0 and QoS 1 are supported; QoS 2 raises
:class:`UnsupportedQoSError`.
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
    # Lazy PEP 562 import: client is the largest module, so a board that
    # imports chumicro_mqtt but never builds an MQTTClient pays no RAM for it.
    if name in ("InboundPublish", "MQTTClient", "ProtocolState", "WhenOversized"):
        # Collect first so the big module compiles into a freshly swept heap.
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
    "topic_matches",
]

gc.collect()
