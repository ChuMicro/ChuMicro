"""Core ``KVStore`` class + exception hierarchy.

Mapping-shaped (``store[key]`` / ``store["k"] = v`` / ``del
store["k"]`` / ``"k" in store`` / iter) plus three explicit lifecycle
methods (``commit``, ``commit_if_changed``, ``reload``).

Backend selection is per-runtime via ``backend="auto"`` with explicit
overrides accepted.

``MemoryBackend`` is lazy-imported (only the CPython fall-through and
``backend="memory"`` paths touch it) — saves ~600-800 B of heap on
device imports.  ``msgpack`` and ``Backend`` stay at module top:
msgpack runs on every commit/load (lazy overhead would dominate);
``Backend`` is needed for the parameter type hint MP evaluates at
function-def time.
"""

import sys

from chumicro_msgpack import packb, unpackb

from chumicro_kvstore._backends.base import Backend


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
        self._data: dict[str, object] = {}
        self._last_payload: bytes = b""
        self._is_corrupt: bool = False
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
            self._is_corrupt = True
            return
        if not payload:
            self._data = {}
            self._last_payload = b""
            return
        loaded = unpackb(payload)
        if not isinstance(loaded, dict):
            self._data = {}
            self._last_payload = b""
            self._is_corrupt = True
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
            self._is_corrupt = False
            return
        loaded = unpackb(payload)
        if not isinstance(loaded, dict):
            raise KVStoreCorrupt("payload is not a dict")
        self._data = dict(loaded)
        self._last_payload = bytes(payload)
        self._is_corrupt = False

    def commit(self) -> None:
        """Encode the current dict and persist it through the backend.

        Raises:
            KVStoreFull: Encoded payload exceeds ``capacity``.
        """
        payload = packb(self._data)
        if len(payload) > self._backend.capacity:
            raise KVStoreFull(
                f"payload size {len(payload)} exceeds capacity {self._backend.capacity}"
            )
        self._backend.save(payload)
        self._last_payload = payload
        self._is_corrupt = False

    def commit_if_changed(self) -> bool:
        """Commit only if the encoded payload differs from last persisted.

        First-line wear defense for raw-flash backends.  Returns
        ``True`` when a write happened, ``False`` when skipped.
        """
        payload = packb(self._data)
        if payload == self._last_payload:
            return False
        if len(payload) > self._backend.capacity:
            raise KVStoreFull(
                f"payload size {len(payload)} exceeds capacity {self._backend.capacity}"
            )
        self._backend.save(payload)
        self._last_payload = payload
        self._is_corrupt = False
        return True

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
        """Return ``self[key]`` if present else *default*."""
        return self._data.get(key, default)

    def keys(self):
        """Return a view of the current keys."""
        return self._data.keys()

    def items(self):
        """Return a view of the current ``(key, value)`` pairs."""
        return self._data.items()

    def values(self):
        """Return a view of the current values."""
        return self._data.values()

    def pop(self, key: str, *default: object) -> object:
        """Remove *key* and return its value; fall back to *default*.

        Args:
            key: Key to remove.
            default: Returned when *key* is absent.  When omitted,
                ``KeyError`` is raised on missing keys (dict semantics).
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
    def capacity(self) -> int:
        """Bytes available on this backend for the encoded payload."""
        return self._backend.capacity

    @property
    def bytes_used(self) -> int:
        """Encoded size of the *current* in-memory dict."""
        return len(packb(self._data))

    @property
    def is_corrupt(self) -> bool:
        """``True`` after a failed-integrity load; cleared by the next successful commit or reload."""
        return self._is_corrupt

    @property
    def backend_name(self) -> str:
        """Stable identifier for the active backend.

        One of ``"nvm"``, ``"nvs"``, ``"littlefs"``, ``"memory"``, or a
        custom name on injected test backends.
        """
        return self._backend.name
