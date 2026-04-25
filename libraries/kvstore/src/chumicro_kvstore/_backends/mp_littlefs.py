"""MicroPython LittleFS backend.

Persists the encoded msgpack payload as a single file on the
LittleFS root: ``/_chu_kv.msgpack``.  The leading underscore keeps
the file out of the way of listing-sorted file managers so it
doesn't surface as the user's first file.

Atomicity comes from LittleFS's atomic-rename guarantee — writes
land in a temp file (``/_chu_kv.msgpack.tmp``) which is renamed
over the canonical path only after ``os.sync()``.  A power loss
mid-write either leaves the old file intact (rename never
happened) or commits the new file (rename completed); the file
system never exposes a partial-write state.  No CRC framing —
LittleFS itself wear-levels and verifies block integrity.

The backend accepts an injected filesystem substrate so host-side
tests can exercise the write / read / rename loop without a Pi
Pico W board — pass any object exposing ``open``, ``rename``,
``remove``, and ``sync`` matching the shapes the runtime exposes.
"""

from chumicro_kvstore._backends.base import Backend


class MpLittlefsBackend(Backend):
    """MP LittleFS backend.

    Args:
        path: Path to the canonical payload file.  Default is
            ``/_chu_kv.msgpack`` (Decision 0034 §7).  Override for
            tests or boards with mounted-elsewhere filesystems.
        filesystem: Optional filesystem-shaped substrate (must
            expose ``open``, ``rename(src, dst)``, ``remove(path)``,
            and ``sync()``).  When ``None`` (default), uses the
            live ``os`` module and built-in ``open`` — only
            available where a real filesystem is mounted.
        capacity: Maximum payload size in bytes.  Defaults to 16 KB
            — generous for most LittleFS partitions, bounded so a
            runaway store doesn't fill the whole filesystem.
            Override on boards with custom layouts.
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
        """Build a default filesystem substrate using the runtime.

        Wraps ``builtins.open`` + ``os.rename`` + ``os.remove`` +
        ``os.sync`` (or a noop) into a tiny shim object that the
        backend's load / save methods talk to.  Lets host tests
        replace just this shim instead of monkey-patching globals.
        """
        import builtins
        import os

        class _RuntimeFs:
            open = staticmethod(builtins.open)
            rename = staticmethod(os.rename)
            remove = staticmethod(os.remove)
            sync = staticmethod(getattr(os, "sync", lambda: None))

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
        from chumicro_kvstore.core import KVStoreFull

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
