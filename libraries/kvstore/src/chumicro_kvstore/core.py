"""``KVStore``, its exceptions, and ``Backend``, the base class of the built-in backends."""

import gc
import sys

from chumicro_msgpack import packb, unpackb


class KVStoreError(Exception):
    """Base class of ``KVStoreFull`` and ``KVStoreCorrupt``.

    ``except KVStoreError:`` catches both.
    """


class KVStoreFull(KVStoreError):
    """Raised when the packed values take more than ``capacity`` bytes.

    ``commit()`` and ``commit_if_changed()`` raise it before writing, so the
    store saves nothing and the values in memory stay as they were.
    """


class KVStoreCorrupt(KVStoreError):
    """Raised by ``reload()`` when the saved bytes are damaged.

    The bytes fail the backend's check, are not valid msgpack, or do not
    unpack to a dict. Creating a ``KVStore`` catches it and sets
    ``is_corrupt`` instead.
    """


class Backend:
    """Base class of the built-in backends, the storage that holds a ``KVStore``'s bytes.

    A subclass sets ``name`` and ``capacity`` and overrides ``load()`` and
    ``save(payload)``.
    """

    # A plain class, not typing.Protocol: MicroPython has no typing module.
    name: str = "base"
    capacity: int = 0

    def load(self) -> bytes | bytearray:
        raise NotImplementedError

    def save(self, payload: bytes) -> None:
        raise NotImplementedError

    def _check_capacity(self, payload: bytes) -> None:
        # One guard for every backend's save(). Capacity 0 means unbounded.
        if 0 < self.capacity < len(payload):
            raise KVStoreFull(
                f"payload size {len(payload)} exceeds "
                f"{self.name} capacity {self.capacity}"
            )


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
    """``KVStore`` holds a dict in memory and saves it to the board's flash or NVM on ``commit()``.

    The saved values survive a reset or a power cut. ``KVStore()`` reads the
    saved bytes once. After that ``store[key]``, ``store[key] = value``,
    ``del store[key]``, ``key in store``, ``len(store)``, and
    ``for key in store`` work on the dict in memory, as do ``get``, ``keys``,
    ``items``, ``values``, ``pop``, ``clear``, and ``update``. A change stays
    in memory until ``commit()`` or ``commit_if_changed()`` saves it.

    ``chumicro_msgpack`` packs the values, which limits what a value can be:
    ``None``, a ``bool``, ``int``, ``float``, ``str``, or ``bytes``, or a
    ``list`` or ``dict`` of those, nested at most 8 deep. An ``int`` lies
    between ``-2**31`` and ``2**32 - 1``, and between ``-2**30`` and
    ``2**30 - 1`` on CircuitPython. A ``float`` saves as 32 bits, about 7
    significant digits.

    Damaged saved data leaves the new store empty with ``is_corrupt`` set,
    so the program keeps running.

    Args:
        backend: Where the bytes go. ``"auto"`` picks ``"nvm"``
            (``microcontroller.nvm``) on CircuitPython, ``"nvs"``
            (``esp32.NVS``) on MicroPython boards with the ``esp32`` module,
            ``"littlefs"`` (the file ``/_chu_kv.msgpack``) on other
            MicroPython boards, and ``"memory"`` on CPython. One of those
            names skips the choice and uses that backend. An object with a
            ``name`` string, a ``capacity`` in bytes (``0`` for no limit), a
            ``load()`` that returns the saved bytes (empty when nothing is
            saved), and a ``save(payload)`` that stores them works as a
            backend too. Its ``load()`` raises ``KVStoreCorrupt`` for damaged
            bytes.

    Attributes:
        capacity: Most bytes ``commit()`` saves. The backend sets it: the NVM
            size minus a 10-byte header for ``"nvm"``, 512 for ``"nvs"``,
            16384 for ``"littlefs"``, and ``sys.maxsize`` for ``"memory"``.
            A backend object passed as ``backend`` sets any other limit
            through its own ``capacity``.
        backend_name: The backend's ``name``, such as ``"nvm"``.
        is_corrupt: ``True`` when the saved data was damaged and the store
            started empty. The next successful ``commit()`` or ``reload()``
            sets it back to ``False``.

    Raises:
        ValueError: ``backend`` is an unknown name, or the board's NVM holds
            10 bytes or fewer.
        RuntimeError: The named backend's hardware module is missing, such as
            ``"nvm"`` off CircuitPython or ``"nvs"`` without ``esp32``.
    """

    def __init__(self, backend: Backend | str = "auto") -> None:
        self._backend: Backend = _resolve_backend(backend)
        self.capacity: int = self._backend.capacity
        self.backend_name: str = self._backend.name
        self._data: dict[str, object] = {}
        self._last_payload: bytes = b""
        self.is_corrupt: bool = False
        self._dirty: bool = False
        try:
            self.reload()
        except KVStoreCorrupt:
            self._data = {}
            self._last_payload = b""
            self.is_corrupt = True

    def reload(self) -> None:
        """Drop unsaved changes and read the saved values back from the backend.

        An empty backend gives an empty store. A successful ``reload()`` sets
        ``is_corrupt`` to ``False``.

        Raises:
            KVStoreCorrupt: The saved bytes are damaged. The values in memory
                stay as they were.
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
        # Loading and decoding leave temporary buffers behind. Collecting now
        # returns that heap at once, before the next automatic collection.
        del payload, loaded
        gc.collect()

    def commit(self) -> None:
        """Pack every value and save the bytes through the backend, changed or not.

        Each save writes flash. Flash wears out after many writes, so code
        that saves in a loop or on a timer calls ``commit_if_changed()``
        instead. A value msgpack cannot pack makes ``commit()`` raise the
        packer's error before anything is saved.

        Raises:
            KVStoreFull: The packed values take more than ``capacity`` bytes.
        """
        self._persist(packb(self._data))

    def commit_if_changed(self) -> bool:
        """Save the values only when they differ from the saved copy, and report whether it saved.

        ``commit_if_changed()`` returns ``False`` at once when no
        ``store[key] = value``, ``del``, ``pop``, ``clear``, or ``update`` ran
        since the last save or ``reload()``. Otherwise it packs the values and
        saves only when the bytes differ from the saved bytes. A change inside
        a stored list or dict, such as ``store["log"].append(1)``, marks
        nothing. Assigning the key again marks it.

        Returns:
            ``True`` when it saved, ``False`` when it skipped the save.

        Raises:
            KVStoreFull: The packed values take more than ``capacity`` bytes.
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
        """Return the value for ``key``, or ``default`` when ``key`` is missing."""
        return self._data.get(key, default)

    def keys(self):
        """Return a view of the keys in memory, as ``dict.keys()`` does."""
        return self._data.keys()

    def items(self):
        """Return a view of the ``(key, value)`` pairs in memory, as ``dict.items()`` does."""
        return self._data.items()

    def values(self):
        """Return a view of the values in memory, as ``dict.values()`` does."""
        return self._data.values()

    def pop(self, key: str, *default: object) -> object:
        """Remove ``key`` and return its value, or return ``default`` when ``key`` is missing.

        Raises:
            KeyError: ``key`` is missing and no ``default`` was given.
        """
        if default:
            value = self._data.pop(key, default[0])
        else:
            # Mark dirty only after the pop: a KeyError changes nothing, so
            # the next commit_if_changed() must not re-encode for it.
            value = self._data.pop(key)
        self._dirty = True
        return value

    def clear(self) -> None:
        """Remove every key from memory. The saved copy stays until the next save."""
        self._data.clear()
        self._dirty = True

    def update(self, other: dict[str, object]) -> None:
        """Copy every key and value from ``other`` into the store, replacing existing keys."""
        self._data.update(other)
        self._dirty = True

    @property
    def bytes_used(self) -> int:
        """Bytes the values in memory take once packed, saved or not.

        ``commit()`` raises ``KVStoreFull`` when ``bytes_used`` is above a
        nonzero ``capacity``. Each read packs the whole dict.
        """
        return len(packb(self._data))
