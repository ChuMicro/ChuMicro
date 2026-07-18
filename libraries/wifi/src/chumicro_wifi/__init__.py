"""Unified wifi supervisor across CircuitPython, MicroPython, and CPython.

Exports :class:`WifiService`, :class:`WifiConfig`, and :class:`WifiState`.
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
