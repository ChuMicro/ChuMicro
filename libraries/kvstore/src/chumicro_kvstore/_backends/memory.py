"""In-memory backend — CPython default + ``FakeKVStore`` substrate.

Stores the encoded payload in process memory; no persistence across
process boundary by default.  *initial* seeds a known starting state.

*capacity* is configurable so tests can simulate small-NVM edge
cases without owning a real low-memory board.
"""

import sys

from chumicro_kvstore.core import Backend, KVStoreCorrupt, KVStoreFull


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
            raise KVStoreCorrupt("memory backend marked corrupt")
        return self._payload

    def save(self, payload: bytes) -> None:
        """Store *payload* verbatim.

        Raises:
            KVStoreFull: Payload exceeds the configured capacity.
        """
        if len(payload) > self.capacity:
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
