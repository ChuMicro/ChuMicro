"""MicroPython ``esp32.NVS`` backend (Slice 3 — placeholder).

The real implementation — namespace ``"chu_kv"``, one ``set_blob`` per
key, msgpack-encoded values — lands in Phase 3b Slice 3 once
hardware-verified on a plugged-in MP-ESP32 board.
"""

from __future__ import annotations

from chumicro_kvstore._backends.base import Backend


class MpNvsBackend(Backend):
    """MP ESP32 NVS backend.  Implementation pending Slice 3."""

    name = "nvs"

    def __init__(self) -> None:
        raise NotImplementedError(
            "MpNvsBackend lands in Phase 3b Slice 3 — see Decision 0034 §6."
        )
