"""Core ``KVStore`` class, exception hierarchy, and ``Backend`` ABC.

``MemoryBackend`` is lazy-imported (only the CPython fall-through and
``backend="memory"`` paths touch it) — saves ~600-800 B of heap on
device imports.  ``msgpack`` stays at module top: it runs on every
commit/load and lazy overhead would dominate.  ``Backend`` lives
alongside the exceptions so backends import their ABC + exception
classes from one place, breaking the cycle that would otherwise
require per-method lazy imports.
"""

import sys

from chumicro_msgpack import packb, unpackb


class KVStoreError(Exception):
    """Base for every kvstore-specific failure."""


class KVStoreFull(KVStoreError):
    """A commit would exceed ``capacity``.

    The store's in-memory state is unchanged; callers that catch this
    typically remove a key and retry.
    """


class KVStoreCorrupt(KVStoreError):
    """Persisted state failed integrity check on load.

    Raised from explicit ``reload()`` only — auto-load on construction
    surfaces corruption via the ``is_corrupt`` property and resets the
    store to empty so the app can keep running.
    """


class Backend:
    """Backend protocol every concrete backend implements.

    A backend is a thin shim around the substrate-specific persistence
    mechanism (CP NVM byte slab, MP NVS namespace, MP LittleFS file,
    in-memory dict).  It deals in ``bytes`` payloads — the msgpack
    codec lives in ``KVStore``, so backends never decode.

    ``load()`` returns the persisted bytes (``b""`` for a blank
    substrate) and raises ``KVStoreCorrupt`` on integrity-check failure
    (CP NVM's CRC mismatch is the canonical case).  ``save(payload)``
    overwrites the persisted state and raises ``KVStoreFull`` if the
    substrate can't accept that many bytes.

    ``capacity`` is honored by ``KVStore`` *before* ``save`` is called,
    so backends only need to enforce it as a defensive last line.
    ``name`` is the stable identifier surfaced by
    ``KVStore.backend_name``.  Kept as a class rather than a
    ``Protocol`` because MicroPython has no ``typing`` module.
    """

    name: str = "base"
    capacity: int = 0

    def load(self) -> bytes:
        raise NotImplementedError

    def save(self, payload: bytes) -> None:
        raise NotImplementedError


def _select_backend() -> Backend:
    """Pick the best backend for this runtime.

    CP / MP branches are exercised by per-runtime functional suites
    under ``functional_tests/``; CPython tests can't reach them.
    """
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
    # CPython fall-through — MemoryBackend is lazy-imported here so
    # device runtimes never pay its ~700 B import cost.
    from chumicro_kvstore._backends.memory import MemoryBackend  # noqa: PLC0415
    return MemoryBackend()


def _resolve_backend(backend: Backend | str) -> Backend:
    """Coerce a backend argument to a concrete instance."""
    if not isinstance(backend, str):
        return backend
    if backend == "auto":
        return _select_backend()
    if backend == "memory":
        # Lazy: device runtimes never reach this path under "auto",
        # so importing MemoryBackend at module top would waste ~700
        # bytes of on-device heap.
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
    """Persisted key-value store with a mapping-shaped public API.

    Args:
        backend: Backend selection — ``"auto"`` (default; per-runtime
            choice), ``"memory"``, ``"nvm"``, ``"nvs"``, ``"littlefs"``,
            or a concrete backend instance for tests.
    """

    def __init__(self, backend: Backend | str = "auto") -> None:
        self._backend: Backend = _resolve_backend(backend)
        self.capacity: int = self._backend.capacity
        self.backend_name: str = self._backend.name
        self._data: dict[str, object] = {}
        self._last_payload: bytes = b""
        self.is_corrupt: bool = False
        self._auto_load()

    # --- lifecycle -------------------------------------------------

    def _auto_load(self) -> None:
        """Read backend on construction; reset to empty on corruption.

        Construction-time corruption never raises — it would force the
        caller to handle a "store is broken" path before the app can
        even start.  Instead, the store reports the event via
        ``is_corrupt`` and behaves as empty.  ``reload()`` is the
        explicit form that callers use when they want the exception.
        """
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
            # Malformed framing (truncated / over-length / trailing /
            # too-deep) — unpackb is a trusting decoder and now rejects
            # these loudly.  Same outcome as a non-dict payload: report
            # corruption, behave empty, never raise at construction.
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
        payload = self._backend.load()  # may raise KVStoreCorrupt
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
        """Commit only if the encoded payload differs from last persisted.

        First-line wear defense for raw-flash backends.  Returns
        ``True`` when a write happened, ``False`` when skipped.
        """
        payload = packb(self._data)
        if payload == self._last_payload:
            return False
        self._persist(payload)
        return True

    def _persist(self, payload: bytes) -> None:
        """Capacity-check + save + state update — shared by both commit paths."""
        if len(payload) > self.capacity:
            raise KVStoreFull(
                f"payload size {len(payload)} exceeds capacity {self.capacity}"
            )
        self._backend.save(payload)
        self._last_payload = payload
        self.is_corrupt = False

    # --- mapping-shaped API ----------------------------------------

    def __getitem__(self, key: str) -> object:
        return self._data[key]

    def __setitem__(self, key: str, value: object) -> None:
        self._data[key] = value

    def __delitem__(self, key: str) -> None:
        del self._data[key]

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
        """Remove *key* and return its value; fall back to *default* if given.

        The variadic *default lets the caller distinguish "no default
        supplied" (raise ``KeyError`` on missing) from "default is
        ``None``" — same idiom as ``dict.pop``.
        """
        if default:
            return self._data.pop(key, default[0])
        return self._data.pop(key)

    def clear(self) -> None:
        """Remove every key from the in-memory dict (commit not implied)."""
        self._data.clear()

    def update(self, other: dict[str, object]) -> None:
        """Merge *other* into the in-memory dict (commit not implied)."""
        self._data.update(other)

    # --- introspection ---------------------------------------------

    @property
    def bytes_used(self) -> int:
        """Encoded size of the *current* in-memory dict (not the persisted payload)."""
        return len(packb(self._data))
