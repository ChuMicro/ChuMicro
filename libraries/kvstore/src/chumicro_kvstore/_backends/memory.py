"""In-memory backend — CPython default + ``FakeKVStore`` substrate.

Stores the encoded payload in process memory.  No persistence across
process boundary by default.  The optional *initial* argument lets
test setups seed a known starting state.

Capacity is configurable so downstream tests can simulate small-NVM
edge cases without owning a SAMD21 (Decision 0034 §8).
"""

import sys

from chumicro_kvstore._backends.base import Backend


class MemoryBackend(Backend):
    """Volatile backend that round-trips ``bytes`` payloads in-process.

    Args:
        initial: Optional starting payload (msgpack-encoded bytes).
            Empty / omitted ⇒ blank store.
        capacity: Override the (effectively unbounded) default size
            limit.  Useful in tests that need to drive ``KVStoreFull``.
    """

    name = "memory"

    def __init__(
        self,
        *,
        initial: bytes | None = None,
        capacity: int | None = None,
    ) -> None:
        self.capacity = capacity if capacity is not None else sys.maxsize
        self._payload: bytes = bytes(initial) if initial else b""
        self._corrupt: bool = False

    def load(self) -> bytes:
        """Return the stored payload bytes (``b""`` if never saved)."""
        if self._corrupt:
            from chumicro_kvstore.core import KVStoreCorrupt
            raise KVStoreCorrupt("memory backend marked corrupt")
        return self._payload

    def save(self, payload: bytes) -> None:
        """Store *payload* verbatim.

        Raises:
            KVStoreFull: Payload exceeds the configured capacity.
        """
        if len(payload) > self.capacity:
            from chumicro_kvstore.core import KVStoreFull
            raise KVStoreFull(
                f"payload size {len(payload)} exceeds capacity {self.capacity}"
            )
        self._payload = bytes(payload)
        self._corrupt = False

    # --- test hooks -------------------------------------------------

    def force_corrupt(self) -> None:
        """Mark the backend as corrupt; next ``load`` raises.

        Lets ``FakeKVStore`` and tests exercise the corruption path
        without touching real flash.
        """
        self._corrupt = True

    def reset_corrupt(self) -> None:
        """Clear the corrupt flag."""
        self._corrupt = False
