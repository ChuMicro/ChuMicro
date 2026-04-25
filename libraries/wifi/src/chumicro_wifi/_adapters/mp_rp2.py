"""MicroPython Pi Pico W (CYW43 / RP2040) adapter (Slice 3 — placeholder).

Real implementation lands in Phase 3a Slice 3.  Applies
``wlan.config(pm=0xa11140)`` to disable CYW43 power-save when
``WifiConfig.power_save`` is ``False`` (Decision 0029 §wifi-
ownership-stance — eliminates idle unresponsiveness).
"""

from chumicro_wifi._adapters.base import WifiAdapter


class MpRp2WifiAdapter(WifiAdapter):
    """MP CYW43 adapter.  Implementation pending Slice 3."""

    name = "mp_rp2"

    def __init__(self):
        raise NotImplementedError(
            "MpRp2WifiAdapter lands in Phase 3a Slice 3 — see "
            "plans/workstreams/project-workspace.md Phase 3a."
        )
