"""``chumicro_wifi`` joins a wifi network and rejoins it after a drop, on CircuitPython,
MicroPython, and CPython.

``WifiService`` does the work.  It takes a ``WifiConfig`` holding the network
name, password, and retry timing, and the main loop calls its ``check`` and
``handle`` methods.  ``WifiState`` names the values ``WifiService.state`` takes.
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
