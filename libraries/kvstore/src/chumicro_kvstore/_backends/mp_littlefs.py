"""MicroPython LittleFS backend.

Persists the msgpack payload as ``/_chu_kv.msgpack`` (leading
underscore keeps it out of file-manager listings).

Atomicity comes from LittleFS's atomic-rename: writes land in
``/_chu_kv.msgpack.tmp`` and rename over the canonical path only
after ``os.sync()``.  Power loss mid-write either leaves the old
file intact or commits the new one — never a partial state.  No
CRC framing — LittleFS wear-levels and verifies block integrity.

Tests inject a filesystem substrate exposing ``open``, ``rename``,
``remove``, and ``sync``.
"""

__chumicro_runtimes__ = ("micropython",)

import builtins
import os

from chumicro_kvstore.core import Backend, KVStoreFull


class _RuntimeFs:
    """Default filesystem shim — wraps ``builtins.open`` + ``os.{rename,remove,sync}``.

    Defined at module scope so the class object is allocated once at
    import rather than once per default-arg backend construction.
    ``getattr(os, "sync", lambda: None)`` keeps the rp2 MP port (no
    ``os.sync``) working — the rename itself is atomic on LittleFS.
    """

    open = staticmethod(builtins.open)
    rename = staticmethod(os.rename)
    remove = staticmethod(os.remove)
    sync = staticmethod(getattr(os, "sync", lambda: None))


class MpLittlefsBackend(Backend):
    """MP LittleFS backend.

    ``path`` defaults to ``/_chu_kv.msgpack``; ``filesystem`` defaults
    to the module's runtime shim and accepts any object exposing
    ``open`` / ``rename`` / ``remove`` / ``sync``.  ``capacity``
    defaults to 16 KB — generous for most partitions, bounded so a
    runaway store can't fill the whole filesystem.
    """

    DEFAULT_PATH = "/_chu_kv.msgpack"
    DEFAULT_CAPACITY = 16384
    TMP_SUFFIX = ".tmp"

    name = "littlefs"

    def __init__(self, path=None, filesystem=None, capacity=None):
        self._path = path if path is not None else self.DEFAULT_PATH
        self._tmp_path = self._path + self.TMP_SUFFIX
        self._fs = filesystem if filesystem is not None else self._acquire_runtime_fs()
        self.capacity = capacity if capacity is not None else self.DEFAULT_CAPACITY

    @staticmethod
    def _acquire_runtime_fs():
        """Return the module-level runtime filesystem shim."""
        return _RuntimeFs

    def load(self) -> bytes:
        """Return the file contents, or ``b""`` if the file does not exist.

        Missing file is treated as a blank substrate, no corruption
        event — the canonical first-boot answer.
        """
        try:
            handle = self._fs.open(self._path, "rb")
        except OSError:
            return b""
        try:
            return handle.read()
        finally:
            handle.close()

    def save(self, payload: bytes) -> None:
        """Write *payload* atomically: tmp file → sync → rename.

        Raises:
            KVStoreFull: ``payload`` exceeds capacity.
        """
        if len(payload) > self.capacity:
            raise KVStoreFull(
                f"payload size {len(payload)} exceeds LittleFS capacity {self.capacity}"
            )

        handle = self._fs.open(self._tmp_path, "wb")
        try:
            handle.write(payload)
        finally:
            handle.close()
        # Sync before rename so the bytes hit flash before the
        # directory entry flips.  LittleFS makes the rename itself
        # atomic; the sync ensures the *contents* aren't half-written
        # at the moment the rename commits.
        self._fs.sync()
        self._fs.rename(self._tmp_path, self._path)
