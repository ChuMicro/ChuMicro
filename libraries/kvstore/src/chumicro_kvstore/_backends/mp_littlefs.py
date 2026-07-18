__chumicro_runtimes__ = ("micropython",)

import builtins
import os

from chumicro_kvstore.core import Backend, KVStoreFull


class _RuntimeFs:
    open = staticmethod(builtins.open)
    rename = staticmethod(os.rename)
    remove = staticmethod(os.remove)
    # rp2 MicroPython has no os.sync; the LittleFS rename is atomic anyway.
    sync = staticmethod(getattr(os, "sync", lambda: None))


class MpLittlefsBackend(Backend):
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
        try:
            handle = self._fs.open(self._path, "rb")
        except OSError:
            return b""
        try:
            return handle.read()
        finally:
            handle.close()

    def save(self, payload: bytes) -> None:
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
            try:
                self._fs.remove(self._tmp_path)
            except OSError:
                pass
            raise
        # Sync before rename so payload bytes reach flash before the directory entry flips.
        self._fs.sync()
        self._fs.rename(self._tmp_path, self._path)
