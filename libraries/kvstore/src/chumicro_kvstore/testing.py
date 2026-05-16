"""Test helpers for libraries that depend on ``chumicro-kvstore``.

Downstream consumers import ``FakeKVStore`` rather than inventing
ad-hoc mocks.

Example::

    from chumicro_kvstore.testing import FakeKVStore

    store = FakeKVStore(capacity=256)        # simulate SAMD21 NVM
    store["boot_count"] = 1
    store.commit()
    store.simulate_corrupt()                 # force is_corrupt next load
"""

#: Test-support: PyPI sdist / wheel only -- bundles and product /
#: app / functional device deploys exclude it; the on-device unit
#: sweep is the one path that stages it.
__chumicro_test_support__ = True

from chumicro_kvstore._backends.memory import MemoryBackend
from chumicro_kvstore.core import KVStore


class FakeKVStore(KVStore):
    """In-memory ``KVStore`` with explicit corruption + capacity hooks.

    Wraps ``MemoryBackend`` so every assertion downstream tests write
    against the real ``KVStore`` API exercises the same code path the
    production runtime takes.

    Args:
        capacity: Optional capacity override (bytes).  Drives the
            ``KVStoreFull`` failure path in downstream tests.
        initial_payload: Optional pre-seeded msgpack payload.
        record_calls: When ``True``, every public-API call appends an
            entry to ``self.calls`` for assertion.
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

        The next ``reload()`` (or ``KVStore`` re-construction) will
        surface a corruption event.  In-memory state stays intact
        until explicitly reloaded, mirroring the production behavior.
        """
        self._memory_backend.force_corrupt()

    def reset_corrupt(self) -> None:
        """Clear the simulated-corrupt flag."""
        self._memory_backend.reset_corrupt()

    def set_capacity(self, capacity: int) -> None:
        """Adjust the simulated capacity mid-test.

        Lets tests cross the ``KVStoreFull`` threshold deterministically
        without manufacturing a giant payload.
        """
        self._memory_backend.capacity = capacity

    @property
    def raw_payload(self) -> bytes:
        """Return the raw msgpack bytes currently held by the backend.

        Useful for round-trip assertions without round-tripping through
        the public reload path.
        """
        return self._memory_backend._payload  # noqa: SLF001 - test helper
