"""MicroPython LittleFS backend (Slice 4 — placeholder).

The real implementation — single ``/_chu_kv.msgpack`` file with
tmpfile + rename atomicity — lands in Phase 3b Slice 4 once
hardware-verified on a plugged-in MP-Pico-W board.
"""

from __future__ import annotations

from chumicro_kvstore._backends.base import Backend


class MpLittlefsBackend(Backend):
    """MP LittleFS backend.  Implementation pending Slice 4."""

    name = "littlefs"

    def __init__(self) -> None:
        raise NotImplementedError(
            "MpLittlefsBackend lands in Phase 3b Slice 4 — see Decision 0034 §7."
        )
