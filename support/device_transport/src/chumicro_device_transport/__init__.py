"""Device transport layer for ChuMicro device testing.

Provides transport implementations for deploying code and running tests
on MicroPython and CircuitPython hardware.  See Decision 0027.

Transport protocol (duck-typed)::

    connect() -> None
    stage(source_dirs, test_files, harness_source) -> None
    execute(bootstrap_script) -> str
    soft_reset() -> None
    reset() -> None
    disconnect() -> None
"""

from .circuitpython_bootstrap import build_circuitpython_bootstrap
from .circuitpython_transport import (
    CircuitpythonTransport,
    CircuitpythonTransportError,
    SerialPort,
    find_circuitpy_drive,
)
from .micropython_transport import MicropythonTransport
from .testing import FakeTransport

__all__ = [
    "CircuitpythonTransport",
    "CircuitpythonTransportError",
    "FakeTransport",
    "MicropythonTransport",
    "SerialPort",
    "build_circuitpython_bootstrap",
    "find_circuitpy_drive",
]
