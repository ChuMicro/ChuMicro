"""Non-blocking MQTT 3.1.1 client for CircuitPython, MicroPython, and CPython.

Built on :mod:`chumicro_sockets` (TCP + TLS) and :mod:`chumicro_timing`
(ticks).  Tick-based runner contract: :meth:`MQTTClient.check(now_ms)`
reports whether work is pending and :meth:`handle(now_ms)` does one
slice of progress per call.

QoS 0 and QoS 1 are supported.  QoS 2 raises :class:`UnsupportedQoSError`.
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
    """Lazy-load the client half on first access (PEP 562).

    ``client`` is the fleet's single largest module (~40 KB of source).
    A board that imports ``chumicro_mqtt`` but never builds an
    ``MQTTClient`` — a receive-only or wire-helper-only use — shouldn't
    pin its compiled code objects in RAM, so the module is deferred until
    the first access to one of its symbols.  Constructing the client at
    startup keeps that one-time import cost on a fresh heap (see the guide).
    """
    if name in ("InboundPublish", "MQTTClient", "ProtocolState", "WhenOversized"):
        import chumicro_mqtt.client as _client  # noqa: PLC0415

        return getattr(_client, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    # pyright: ignore[reportUnsupportedDunderAll] — InboundPublish,
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
