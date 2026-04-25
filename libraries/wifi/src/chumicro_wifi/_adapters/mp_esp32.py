"""MicroPython ESP32 ``network.WLAN`` adapter (Slice 2 — placeholder).

Real implementation lands in Phase 3a Slice 2.  Includes the
``wlan.config(reconnects=0)`` call to disable the firmware-level
auto-reconnect supervisor (Decision 0029 §wifi-ownership-stance —
library is the sole supervisor on every runtime).
"""

from chumicro_wifi._adapters.base import WifiAdapter


class MpEsp32WifiAdapter(WifiAdapter):
    """MP ESP32 adapter.  Implementation pending Slice 2."""

    name = "mp_esp32"

    def __init__(self):
        raise NotImplementedError(
            "MpEsp32WifiAdapter lands in Phase 3a Slice 2 — see "
            "plans/workstreams/project-workspace.md Phase 3a."
        )
