__chumicro_runtimes__ = ("micropython",)

import builtins
import os

from chumicro_kvstore.core import Backend


class _RuntimeFilesystem:
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
        self._filesystem = filesystem if filesystem is not None else _RuntimeFilesystem
        self.capacity = capacity if capacity is not None else self.DEFAULT_CAPACITY

    def load(self) -> bytes:
        try:
            handle = self._filesystem.open(self._path, "rb")
        except OSError:
            return b""
        try:
            return handle.read()
        finally:
            handle.close()

    def save(self, payload: bytes) -> None:
        self._check_capacity(payload)

        handle = self._filesystem.open(self._tmp_path, "wb")
        try:
            try:
                handle.write(payload)
            finally:
                handle.close()
        except OSError:
            try:
                self._filesystem.remove(self._tmp_path)
            except OSError:
                pass
            raise
        # Sync before rename so payload bytes reach flash before the directory entry flips.
        self._filesystem.sync()
        self._filesystem.rename(self._tmp_path, self._path)
