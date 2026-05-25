"""Unified wifi supervisor across CircuitPython, MicroPython, and CPython.

The library is the sole wifi supervisor on every runtime.  No
``CIRCUITPY_WIFI_*`` keys, no firmware-level auto-reconnect.

Public API::

    from chumicro_wifi import WifiService, WifiConfig, WifiState
    from chumicro_config import load_runtime_config

    config = load_runtime_config()
    wifi = WifiService(WifiConfig.from_config(config))
    runner.add(wifi)            # tick-based check/handle integration

    # State + IP introspection any time:
    wifi.state                  # "disconnected" | "connecting" | "connected" | ...
    wifi.connected
    wifi.ip
    wifi.last_error

    wifi.on_state_change(lambda old, new: print(old, "->", new))

For tests + downstream library tests::

    from chumicro_wifi.testing import FakeWifi

The three names above import eagerly.  Per-runtime adapter
selection is deferred to :func:`service._select_adapter`, which
lazy-imports the substrate-specific module with a named
``from X import Y`` inside the function body.  Module-level PEP 562
``__getattr__`` lazy attrs do not work here: CircuitPython's
RAM-mode class-as-module stub silently bypasses them.
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
