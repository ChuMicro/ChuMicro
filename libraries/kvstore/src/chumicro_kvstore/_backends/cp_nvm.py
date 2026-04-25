"""CircuitPython ``microcontroller.nvm`` backend (Slice 2 — placeholder).

This module exists so ``backend="nvm"`` resolves on CP and the
auto-detect path picks it up; the real CRC-framed payload codec lands
in Phase 3b Slice 2 once the contract has been hardware-verified on a
plugged-in CP board.
"""

from __future__ import annotations

from chumicro_kvstore._backends.base import Backend


class CpNvmBackend(Backend):
    """CP NVM backend.  Implementation pending Slice 2."""

    name = "nvm"

    def __init__(self) -> None:
        raise NotImplementedError(
            "CpNvmBackend lands in Phase 3b Slice 2 — see Decision 0034 §5."
        )
