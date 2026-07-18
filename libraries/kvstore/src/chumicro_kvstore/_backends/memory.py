import sys

from chumicro_kvstore.core import Backend, KVStoreCorrupt, KVStoreFull


class MemoryBackend(Backend):
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
        if self._corrupt:
            raise KVStoreCorrupt("memory backend marked corrupt")
        return self._payload

    def save(self, payload: bytes) -> None:
        if len(payload) > self.capacity:
            raise KVStoreFull(
                f"payload size {len(payload)} exceeds capacity {self.capacity}"
            )
        self._payload = bytes(payload)
        self._corrupt = False

    def force_corrupt(self) -> None:
        self._corrupt = True

    def reset_corrupt(self) -> None:
        self._corrupt = False
