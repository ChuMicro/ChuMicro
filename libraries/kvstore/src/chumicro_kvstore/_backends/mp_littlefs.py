"""MicroPython LittleFS backend.

Persists the msgpack payload as ``/_chu_kv.msgpack``. Writes go to a
``.tmp`` file and are renamed over the payload only after ``os.sync()``,
so LittleFS's atomic rename leaves either the old file or the new one
after a power loss, never a partial write. There is no CRC framing:
LittleFS verifies block integrity itself.
"""

__chumicro_runtimes__ = ("micropython",)

import builtins
import os

from chumicro_kvstore.core import Backend, KVStoreFull


# Module-scope so this substrate class is built once at import, not once
# per default-arg backend construction.
class _RuntimeFs:
    open = staticmethod(builtins.open)
    rename = staticmethod(os.rename)
    remove = staticmethod(os.remove)
    # rp2 MicroPython has no os.sync; the LittleFS rename is atomic anyway.
    sync = staticmethod(getattr(os, "sync", lambda: None))


class MpLittlefsBackend(Backend):
    """MicroPython LittleFS backend.

    ``path`` defaults to ``/_chu_kv.msgpack`` and ``filesystem`` to the
    module's runtime shim (any object exposing ``open`` / ``rename`` /
    ``remove`` / ``sync``). ``capacity`` defaults to 16 KB, bounded so a
    runaway store cannot fill the filesystem.
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
        return _RuntimeFs

    def load(self) -> bytes:
        """Return the file contents, or ``b""`` if the file is missing.

        A missing file is a blank substrate, not a corruption event.
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
        """Write *payload* atomically via a tmp file, sync, then rename.

        Raises:
            KVStoreFull: ``payload`` exceeds capacity.
        """
        if len(payload) > self.capacity:
            raise KVStoreFull(
                f"payload size {len(payload)} exceeds LittleFS capacity {self.capacity}"
            )

        handle = self._fs.open(self._tmp_path, "wb")
        try:
            try:
                handle.write(payload)
            finally:
                handle.close()
        except OSError:
            # A failed write (e.g. ENOSPC) can leave a partial temp file;
            # remove it before re-raising so it does not eat flash.
            try:
                self._fs.remove(self._tmp_path)
            except OSError:
                pass  # already gone, or the fs can't remove it
            raise
        # Sync before rename so the payload bytes reach flash before the
        # directory entry flips; the rename itself is already atomic.
        self._fs.sync()
        self._fs.rename(self._tmp_path, self._path)
