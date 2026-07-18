"""Test helpers for libraries that depend on ``chumicro-kvstore``.

``FakeKVStore`` gives downstream libraries a real store to test against
instead of hand-rolling a mock.
"""

__chumicro_test_support__ = True

from chumicro_kvstore._backends.memory import MemoryBackend
from chumicro_kvstore.core import KVStore


class FakeKVStore(KVStore):
    """In-memory ``KVStore`` with explicit corruption and capacity hooks.

    Wraps ``MemoryBackend`` so downstream tests exercise the real
    ``KVStore`` API and code path.

    Args:
        capacity: Optional capacity override in bytes, to drive the
            ``KVStoreFull`` path in downstream tests.
        initial_payload: Optional pre-seeded msgpack payload.
        record_calls: When ``True``, each public-API call appends an entry
            to ``self.calls`` for later assertion.
    """

    def __init__(
        self,
        *,
        capacity: int | None = None,
        initial_payload: bytes | None = None,
        record_calls: bool = False,
    ) -> None:
        self._memory_backend = MemoryBackend(
            initial=initial_payload,
            capacity=capacity,
        )
        super().__init__(backend=self._memory_backend)
        self.calls: list[tuple[str, tuple[object, ...]]] = []
        self._record = record_calls

    # --- recording-aware overrides ---------------------------------

    def __setitem__(self, key: str, value: object) -> None:
        if self._record:
            self.calls.append(("__setitem__", (key, value)))
        super().__setitem__(key, value)

    def __delitem__(self, key: str) -> None:
        if self._record:
            self.calls.append(("__delitem__", (key,)))
        super().__delitem__(key)

    def commit(self) -> None:
        if self._record:
            self.calls.append(("commit", ()))
        super().commit()

    def commit_if_changed(self) -> bool:
        if self._record:
            self.calls.append(("commit_if_changed", ()))
        return super().commit_if_changed()

    def reload(self) -> None:
        if self._record:
            self.calls.append(("reload", ()))
        super().reload()

    # --- explicit hooks for tests ----------------------------------

    def simulate_corrupt(self) -> None:
        """Mark the underlying memory backend corrupt.

        The next ``reload()`` surfaces the corruption; in-memory state stays
        intact until then, mirroring production behavior.
        """
        self._memory_backend.force_corrupt()

    def reset_corrupt(self) -> None:
        """Clear the simulated-corrupt flag."""
        self._memory_backend.reset_corrupt()

    def set_capacity(self, capacity: int) -> None:
        """Adjust the simulated capacity mid-test.

        Updates both the backend and the ``KVStore.capacity`` snapshot taken
        at construction, so a raised cap takes effect: the store's own
        pre-check reads that snapshot, not the backend.
        """
        self._memory_backend.capacity = capacity
        self.capacity = capacity

    @property
    def raw_payload(self) -> bytes:
        """Raw msgpack bytes currently held by the backend."""
        return self._memory_backend._payload  # noqa: SLF001 - test helper
