"""Unified wifi supervisor across CircuitPython, MicroPython, and CPython.

Exports :class:`WifiService` (the reconnect state machine), :class:`WifiConfig`
(typed connection settings), and :class:`WifiState` (state-name constants); test
code imports :class:`chumicro_wifi.testing.FakeWifi`. This library is the sole
wifi supervisor on every runtime: no ``CIRCUITPY_WIFI_*`` keys, no firmware-level
auto-reconnect.
"""

import gc

from chumicro_wifi.config import WifiConfig
from chumicro_wifi.service import WifiService, WifiState

__all__ = [
    "WifiConfig",
    "WifiService",
    "WifiState",
]

gc.collect()
