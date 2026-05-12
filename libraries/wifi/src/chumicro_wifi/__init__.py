"""Unified wifi supervisor across CircuitPython, MicroPython, and CPython.

Library is the sole wifi supervisor on every runtime — no
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

The package-level surface is eager (3 imports); per-runtime adapter
selection happens lazily inside :func:`service._select_adapter` via
named ``from X import Y`` — the only form that works under
CircuitPython's RAM-mode class-as-module stub (PEP 562 module-level
``__getattr__`` is silently bypassed by that stub).
"""

from chumicro_wifi.config import WifiConfig
from chumicro_wifi.service import WifiService, WifiState

__all__ = [
    "WifiConfig",
    "WifiService",
    "WifiState",
]
