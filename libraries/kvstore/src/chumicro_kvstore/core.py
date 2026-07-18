"""Core ``KVStore`` class, exception hierarchy, and ``Backend`` ABC."""

import sys

from chumicro_msgpack import packb, unpackb


class KVStoreError(Exception):
    """Base for every kvstore-specific failure."""


class KVStoreFull(KVStoreError):
    """A commit would exceed ``capacity``; the in-memory state is left unchanged."""


class KVStoreCorrupt(KVStoreError):
    """Persisted state failed its integrity check on load."""


class Backend:
    """Interface that every concrete backend implements."""

    # A plain class, not typing.Protocol: MicroPython has no typing module.
    name: str = "base"
    capacity: int = 0

    def load(self) -> bytes:
        raise NotImplementedError

    def save(self, payload: bytes) -> None:
        raise NotImplementedError


def _select_backend() -> Backend:
    runtime_name = sys.implementation.name
    if runtime_name == "circuitpython":  # pragma: no cover - CP runtime path
        from chumicro_kvstore._backends.cp_nvm import CpNvmBackend  # noqa: PLC0415
        return CpNvmBackend()
    if runtime_name == "micropython":  # pragma: no cover - MP runtime path
        try:
            import esp32  # noqa: F401, PLC0415
        except ImportError:
            from chumicro_kvstore._backends.mp_littlefs import MpLittlefsBackend  # noqa: PLC0415
            return MpLittlefsBackend()
        from chumicro_kvstore._backends.mp_nvs import MpNvsBackend  # noqa: PLC0415
        return MpNvsBackend()
    from chumicro_kvstore._backends.memory import MemoryBackend  # noqa: PLC0415
    return MemoryBackend()


def _resolve_backend(backend: Backend | str) -> Backend:
    if not isinstance(backend, str):
        return backend
    if backend == "auto":
        return _select_backend()
    if backend == "memory":
        from chumicro_kvstore._backends.memory import MemoryBackend  # noqa: PLC0415
        return MemoryBackend()
    if backend == "nvm":
        from chumicro_kvstore._backends.cp_nvm import CpNvmBackend  # noqa: PLC0415
        return CpNvmBackend()
    if backend == "nvs":
        from chumicro_kvstore._backends.mp_nvs import MpNvsBackend  # noqa: PLC0415
        return MpNvsBackend()
    if backend == "littlefs":
        from chumicro_kvstore._backends.mp_littlefs import MpLittlefsBackend  # noqa: PLC0415
        return MpLittlefsBackend()
    raise ValueError(f"Unknown backend: {backend!r}")


class KVStore:
    """Persisted key-value store with a mapping-style public API.

    Args:
        backend: ``"auto"``, ``"memory"``, ``"nvm"``, ``"nvs"``, ``"littlefs"``, or a backend instance.
    """

    def __init__(self, backend: Backend | str = "auto") -> None:
        self._backend: Backend = _resolve_backend(backend)
        self.capacity: int = self._backend.capacity
        self.backend_name: str = self._backend.name
        self._data: dict[str, object] = {}
        self._last_payload: bytes = b""
        self.is_corrupt: bool = False
        self._dirty: bool = False
        self._auto_load()

    def _auto_load(self) -> None:
        self._dirty = False
        try:
            payload = self._backend.load()
        except KVStoreCorrupt:
            self._data = {}
            self._last_payload = b""
            self.is_corrupt = True
            return
        if not payload:
            self._data = {}
            self._last_payload = b""
            return
        try:
            loaded = unpackb(payload)
        except ValueError:
            loaded = None
        if not isinstance(loaded, dict):
            self._data = {}
            self._last_payload = b""
            self.is_corrupt = True
            return
        self._data = dict(loaded)
        self._last_payload = bytes(payload)

    def reload(self) -> None:
        """Discard in-memory state and reread from backend.

        Raises:
            KVStoreCorrupt: Backend payload failed integrity check.
        """
        self._dirty = False
        payload = self._backend.load()
        if not payload:
            self._data = {}
            self._last_payload = b""
            self.is_corrupt = False
            return
        try:
            loaded = unpackb(payload)
        except ValueError as error:
            raise KVStoreCorrupt(f"payload is not valid msgpack: {error}") from error
        if not isinstance(loaded, dict):
            raise KVStoreCorrupt("payload is not a dict")
        self._data = dict(loaded)
        self._last_payload = bytes(payload)
        self.is_corrupt = False

    def commit(self) -> None:
        """Encode the current dict and persist it through the backend.

        Raises:
            KVStoreFull: Encoded payload exceeds ``capacity``.
        """
        self._persist(packb(self._data))

    def commit_if_changed(self) -> bool:
        """Commit only when the encoded payload changed since the last persist.

        Returns:
            ``True`` if a write happened, ``False`` if the commit was skipped.
        """
        if not self._dirty:
            return False
        payload = packb(self._data)
        if payload == self._last_payload:
            self._dirty = False
            return False
        self._persist(payload)
        return True

    def _persist(self, payload: bytes) -> None:
        # capacity 0 (the Backend default) means unbounded, not a zero limit.
        if 0 < self.capacity < len(payload):
            raise KVStoreFull(
                f"payload size {len(payload)} exceeds capacity {self.capacity}"
            )
        self._backend.save(payload)
        self._last_payload = payload
        self.is_corrupt = False
        self._dirty = False

    def __getitem__(self, key: str) -> object:
        return self._data[key]

    def __setitem__(self, key: str, value: object) -> None:
        self._data[key] = value
        self._dirty = True

    def __delitem__(self, key: str) -> None:
        del self._data[key]
        self._dirty = True

    def __contains__(self, key: object) -> bool:
        return key in self._data

    def __iter__(self):
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)

    def get(self, key: str, default: object = None) -> object:
        return self._data.get(key, default)

    def keys(self):
        return self._data.keys()

    def items(self):
        return self._data.items()

    def values(self):
        return self._data.values()

    def pop(self, key: str, *default: object) -> object:
        """Remove *key* and return its value, or *default* when supplied."""
        self._dirty = True
        if default:
            return self._data.pop(key, default[0])
        return self._data.pop(key)

    def clear(self) -> None:
        """Remove every key from the in-memory dict (commit not implied)."""
        self._data.clear()
        self._dirty = True

    def update(self, other: dict[str, object]) -> None:
        """Merge *other* into the in-memory dict (commit not implied)."""
        self._data.update(other)
        self._dirty = True

    @property
    def bytes_used(self) -> int:
        """Encoded size of the current in-memory dict, not the persisted payload."""
        return len(packb(self._data))
