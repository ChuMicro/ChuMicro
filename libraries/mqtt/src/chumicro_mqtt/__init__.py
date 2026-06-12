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
)

gc.collect()

from chumicro_mqtt.client import MQTTClient, ProtocolState, WhenOversized  # noqa: E402, I001 - preceded by gc.collect().

__all__ = [
    "MQTTClient",
    "MQTTBackpressureError",
    "MQTTConnectError",
    "MQTTError",
    "MQTTProtocolError",
    "ProtocolState",
    "UnsupportedQoSError",
    "WhenOversized",
]

gc.collect()
