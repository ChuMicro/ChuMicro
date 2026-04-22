"""Device transport layer for ChuMicro device testing.

Provides transport implementations for deploying code and running tests
on MicroPython and CircuitPython hardware.  See Decision 0027.

The transport contract is captured in :mod:`protocol`:

- :class:`TransportProtocol` — minimum every transport must implement.
- :class:`ExtendedTransportProtocol` — adds the CircuitPython RAM-mode
  chunking helpers (``execute_scripts``, ``probe_free_memory``,
  ``inline_script_budget_bytes``).
"""

from .circuitpython_bootstrap import (
    build_circuitpython_bootstrap,
    build_circuitpython_bootstrap_scripts,
)
from .circuitpython_transport import (
    CircuitpythonTransport,
    CircuitpythonTransportError,
    SerialPort,
    find_circuitpy_drive,
)
from .micropython_transport import MicropythonTransport
from .protocol import (
    DeviceImplementation,
    ExtendedTransportProtocol,
    TransportProtocol,
)
from .testing import FakeTransport

__all__ = [
    "CircuitpythonTransport",
    "CircuitpythonTransportError",
    "DeviceImplementation",
    "ExtendedTransportProtocol",
    "FakeTransport",
    "MicropythonTransport",
    "SerialPort",
    "TransportProtocol",
    "build_circuitpython_bootstrap",
    "build_circuitpython_bootstrap_scripts",
    "find_circuitpy_drive",
]
