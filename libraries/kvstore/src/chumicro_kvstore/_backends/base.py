"""Backend protocol every concrete backend implements.

A backend is a thin shim around the substrate-specific persistence
mechanism (CP NVM byte slab, MP NVS namespace, MP LittleFS file,
in-memory dict, …).  It deals in ``bytes`` payloads — the msgpack
codec lives in ``KVStore`` itself, so backends never decode.

Two responsibilities:

1. ``load()`` — return the persisted payload bytes, or ``b""`` for a
   blank substrate.  Raise ``KVStoreCorrupt`` if integrity-check
   framing fails (CP NVM's CRC mismatch is the canonical case).
2. ``save(payload)`` — overwrite the persisted state with *payload*.
   Raise ``KVStoreFull`` if the substrate can't accept that many
   bytes.  Raise ``KVStoreReadOnly`` if the substrate refuses the
   write right now (CP USB-MSC active, …).

The ``capacity`` attribute is honored by ``KVStore`` *before* calling
``save``, so backends only need to enforce it as a defensive last
line.  Backends also expose a stable ``name`` string used by the
``KVStore.backend_name`` property.
"""

from __future__ import annotations


class Backend:
    """Concrete backends inherit and override the four members below.

    Kept as a class rather than a ``Protocol`` because library code
    cannot import ``typing`` (Decision 0021).
    """

    name: str = "base"
    capacity: int = 0

    def load(self) -> bytes:
        """Return the persisted msgpack payload.

        Returns ``b""`` for a blank or never-written substrate.

        Raises:
            KVStoreCorrupt: Integrity check failed.
        """
        raise NotImplementedError

    def save(self, payload: bytes) -> None:
        """Persist *payload* to the substrate.

        Raises:
            KVStoreFull: Payload exceeds substrate capacity.
            KVStoreReadOnly: Substrate refuses writes right now.
        """
        raise NotImplementedError
