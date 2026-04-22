"""chumicro-deploy — host-side device transports and deploy tooling.

Publishable workbench tool (Decision 0032) for deploying code and
running tests on MicroPython and CircuitPython hardware.

Transport contract (Decision 0027) is captured in :mod:`protocol`:

- :class:`TransportProtocol` — minimum every transport must implement.
- :class:`ExtendedTransportProtocol` — adds the CircuitPython RAM-mode
  chunking helpers (``execute_scripts``, ``probe_free_memory``,
  ``inline_script_budget_bytes``).

The :class:`Device` facade bundles runtime identity + connection
details + deploy-mode preference into a single object that
:meth:`Device.create_transport` turns into a concrete
:class:`TransportProtocol`.
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
from .device import Device
from .micropython_transport import MicropythonTransport
from .protocol import (
    DeviceImplementation,
    ExtendedTransportProtocol,
    TransportProtocol,
)
from .result import DeployError, DeployResult
from .testing import FakeTransport

__all__ = [
    "CircuitpythonTransport",
    "CircuitpythonTransportError",
    "DeployError",
    "DeployResult",
    "Device",
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
