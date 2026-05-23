"""Non-blocking MQTT 3.1.1 client for CircuitPython, MicroPython, and CPython.

Built on :mod:`chumicro_sockets` (TCP + TLS) and :mod:`chumicro_timing`
(ticks).  Tick-based runner contract: :meth:`MQTTClient.check(now_ms)`
reports whether work is pending and :meth:`handle(now_ms)` does one
slice of progress per call.

QoS 0 and QoS 1 are supported.  QoS 2 raises :class:`UnsupportedQoSError`.

This module sweeps the GC between and after its submodule imports.
On MicroPython, compile-time scratch (AST nodes, transient tuples,
interned-name artifacts) from loading ``_wire.py`` and ``client.py``
stays resident until auto-GC fires under allocation pressure — which
a successful import never triggers, leaving the scratch interleaved
with the persistent module state.  The explicit collects defragment
that pattern, recovering ~33 KB of contiguous heap on Pi Pico W MP and
restoring TLS handshake headroom that the chain otherwise loses.  On
CPython the calls are benign (cycle collector runs a no-op pass for
non-cyclic code).
"""

import gc as _gc  # noqa: I001 — gc.collect() interleaved with imports is intentional; see module docstring.

from chumicro_mqtt._wire import (
    MQTTBackpressureError,
    MQTTConnectError,
    MQTTError,
    MQTTProtocolError,
    UnsupportedQoSError,
)
_gc.collect()

from chumicro_mqtt.client import MQTTClient, MQTTPublisher, ProtocolState, WhenOversized  # noqa: E402, I001 — gc.collect() interleaved with imports is intentional.

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
]

_gc.collect()
del _gc
