"""MicroPython ``esp32.NVS`` backend.

Persists the msgpack payload as a single blob under key ``"payload"``
in the ``"chu_kv"`` namespace.  Single-blob (rather than per-dict-key)
because MP's ``esp32.NVS`` wrapper doesn't expose key enumeration;
per-key storage would require a manifest blob for marginal wear gain.

No CRC framing here (unlike CP's NVM path): a corrupt blob is caught
when ``unpackb`` rejects its framing on load.  ``esp32.NVS`` is commonly
described as wear-leveled and atomic-on-commit, but this layer neither
provides nor verifies those properties.

Tests inject an ``nvs`` substrate exposing ``set_blob(key, value)``,
``get_blob(key, buffer) -> length``, ``erase_key(key)``, ``commit()``.
"""

__chumicro_runtimes__ = ("micropython",)

import errno

from chumicro_kvstore.core import Backend, KVStoreCorrupt, KVStoreFull

#: ESP-IDF ``ESP_ERR_NVS_NOT_FOUND`` — the "key absent" error code
#: MicroPython's ``esp32.NVS`` surfaces via ``OSError`` on a real board
#: (host fakes use ``errno.ENOENT``).  Any other NVS error means the
#: blob is present but unreadable, which must not read as blank.
_ESP_ERR_NVS_NOT_FOUND = 0x1102


class MpNvsBackend(Backend):
    """MP ESP32 NVS backend.

    ``nvs`` defaults to ``esp32.NVS("chu_kv")``.  Tests inject a fake
    exposing the same ``set_blob`` / ``get_blob(key, buffer) -> length``
    / ``erase_key`` / ``commit`` interface.  ``capacity`` defaults to 512 B,
    sized for small-key state (boot counters, timestamps, short tokens)
    and doubling as the size of the transient read buffer allocated at
    ``load`` time.
    """

    NAMESPACE = "chu_kv"
    PAYLOAD_KEY = "payload"
    DEFAULT_CAPACITY = 512

    name = "nvs"

    def __init__(self, nvs=None, capacity=None):
        if nvs is None:
            nvs = self._acquire_runtime_nvs()
        self._nvs = nvs
        self.capacity = capacity if capacity is not None else self.DEFAULT_CAPACITY

    @staticmethod
    def _acquire_runtime_nvs():
        """Open ``esp32.NVS("chu_kv")`` or raise a clear error."""
        try:
            import esp32  # pragma: no cover - MP-ESP32 runtime path
        except ImportError as error:
            raise RuntimeError(
                "MpNvsBackend requires MicroPython ESP32 (esp32.NVS). "
                "On a host, pass `nvs=<fake>` to test the wire format."
            ) from error
        return esp32.NVS(MpNvsBackend.NAMESPACE)  # pragma: no cover - MP-ESP32 runtime path

    def load(self) -> bytes:
        """Return the stored payload, or ``b""`` for a missing key.

        The read buffer is allocated fresh per call: ``load`` runs at
        construction and on explicit ``reload``, never on the commit
        hot path, so a long-lived ``bytearray(capacity)`` would pin
        RAM without earning the reuse.
        """
        read_buffer = bytearray(self.capacity)
        try:
            length = self._nvs.get_blob(self.PAYLOAD_KEY, read_buffer)
        except OSError as error:
            code = error.args[0] if error.args else None
            if code in (errno.ENOENT, _ESP_ERR_NVS_NOT_FOUND):
                return b""  # key absent: an empty store, not corruption
            # Anything else (buffer too small for the stored blob, type
            # mismatch) means the payload is present but unreadable into
            # our buffer.  Surface it as corrupt so _auto_load reports
            # is_corrupt rather than returning blank — which the store
            # would then overwrite, losing the data.
            raise KVStoreCorrupt(
                f"NVS read failed for key {self.PAYLOAD_KEY!r} (error {code})",
            ) from error
        return bytes(memoryview(read_buffer)[:length])

    def save(self, payload: bytes) -> None:
        """Write ``payload`` and commit.

        Raises:
            KVStoreFull: ``payload`` exceeds capacity.
        """
        if len(payload) > self.capacity:
            raise KVStoreFull(
                f"payload size {len(payload)} exceeds NVS capacity {self.capacity}"
            )
        self._nvs.set_blob(self.PAYLOAD_KEY, payload)
        self._nvs.commit()
