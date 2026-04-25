"""CircuitPython ``wifi.radio`` adapter (Slice 1 — placeholder).

Real implementation lands in Phase 3a Slice 1 once hardware-verified
on a plugged-in CP board.  The class shape is fixed by
``WifiAdapter`` (see ``_adapters/base.py``); this stub raises
``NotImplementedError`` immediately so the auto-detect path resolves
to it on CP without silently falling through to the fake adapter.
"""

from chumicro_wifi._adapters.base import WifiAdapter


class CpWifiAdapter(WifiAdapter):
    """CP ``wifi.radio`` adapter.  Implementation pending Slice 1."""

    name = "cp"

    def __init__(self):
        raise NotImplementedError(
            "CpWifiAdapter lands in Phase 3a Slice 1 — see "
            "plans/workstreams/project-workspace.md Phase 3a."
        )
