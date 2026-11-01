"""``FakeKVStore``, a ``KVStore`` for tests that saves to memory and needs no board."""

__chumicro_test_support__ = True

from chumicro_kvstore._backends.memory import MemoryBackend
from chumicro_kvstore.core import KVStore


class FakeKVStore(KVStore):
    """``FakeKVStore`` runs the real ``KVStore`` code over an in-memory backend.

    Code under test takes it wherever it takes a ``KVStore``. Its extra
    methods make a save too large or the saved bytes damaged on demand.

    Args:
        capacity: Most bytes ``commit()`` saves before raising
            ``KVStoreFull``. ``None`` sets the limit to ``sys.maxsize``.
        initial_payload: Bytes the backend starts with, as if an earlier run
            saved them. Another store's ``raw_payload`` simulates a reboot.
            Bytes that do not unpack to a dict start the store empty with
            ``is_corrupt`` set.
        record_calls: When ``True``, ``calls`` records each ``__setitem__``,
            ``__delitem__``, ``commit``, ``commit_if_changed``, and ``reload``
            call. The first entry is ``("reload", ())``, from ``__init__``.

    Attributes:
        calls: The recorded calls as ``(method_name, args)`` tuples, empty
            unless ``record_calls`` is ``True``.
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
        # Recording state first: KVStore's constructor calls reload(), which
        # dispatches to the recording override below.
        self.calls: list[tuple[str, tuple[object, ...]]] = []
        self._record = record_calls
        super().__init__(backend=self._memory_backend)

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

    def simulate_corrupt(self) -> None:
        """Make the next ``reload()`` raise ``KVStoreCorrupt``.

        The values in memory stay as they are. A ``commit()`` or
        ``reset_corrupt()`` clears the damage.
        """
        self._memory_backend.force_corrupt()

    def reset_corrupt(self) -> None:
        """Undo ``simulate_corrupt()``, so ``reload()`` reads the saved bytes again."""
        self._memory_backend.reset_corrupt()

    def set_capacity(self, capacity: int) -> None:
        """Set the byte limit the next ``commit()`` checks, on the store and its backend."""
        self._memory_backend.capacity = capacity
        self.capacity = capacity

    @property
    def raw_payload(self) -> bytes:
        """Bytes the backend holds: the last saved payload, or ``initial_payload`` before any save."""
        return self._memory_backend._payload  # noqa: SLF001 - test helper
