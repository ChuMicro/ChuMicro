"""Unified wifi supervisor across CircuitPython, MicroPython, and CPython.

Library is the sole wifi supervisor on every runtime
(Decision 0029 §wifi-ownership-stance) — no
``CIRCUITPY_WIFI_*`` keys, no firmware-level auto-reconnect.

Public API::

    from chumicro_wifi import WifiService, WifiConfig, WifiState
    from chumicro_config import load_runtime_config

    config = load_runtime_config()
    wifi = WifiService(WifiConfig.from_dict(config["wifi"]))
    runner.add(wifi)            # tick-based check/handle integration

    # State + IP introspection any time:
    wifi.state                  # "disconnected" | "connecting" | "connected" | ...
    wifi.connected
    wifi.ip
    wifi.last_error

    wifi.on_state_change(lambda old, new: print(old, "->", new))

For tests + downstream library tests::

    from chumicro_wifi.testing import FakeWifi

**Loading shape (Tier A per the lazy-loading research).**  The
package-level surface is small (3 attrs) so eager imports are
correct here — the early prototype tried PEP 562 module
``__getattr__`` for parity with ``chumicro-deploy``, but real
CircuitPython RAM-mode deploys class-as-module stubs that don't
honor PEP 562 (the ``_Mod`` wrapper bypasses module ``__getattr__``
silently).  The lazy benefit lives where it actually pays: the
per-runtime adapter selection inside
:func:`chumicro_wifi.service._select_adapter`, which uses the
named ``from X import Y`` form that *does* work on every deploy
path (same shape as ``chumicro_kvstore._select_backend``).
"""

from chumicro_wifi.config import WifiConfig
from chumicro_wifi.service import WifiService
from chumicro_wifi.state import WifiState

__all__ = [
    "WifiConfig",
    "WifiService",
    "WifiState",
]
