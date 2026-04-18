"""Device transport layer for ChuMicro device testing.

Provides transport implementations for deploying code and running tests
on MicroPython and CircuitPython hardware.  See Decision 0027.

Transport protocol (duck-typed)::

    connect() -> None
    stage(source_dirs, test_files, harness_source) -> None
    execute(bootstrap_script) -> str
    reset() -> None
    disconnect() -> None
"""

from .micropython_transport import MicropythonTransport
from .testing import FakeTransport

__all__ = [
    "FakeTransport",
    "MicropythonTransport",
]

