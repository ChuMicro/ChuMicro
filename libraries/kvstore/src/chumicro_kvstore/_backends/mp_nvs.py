"""MicroPython ``esp32.NVS`` backend.

Persists the msgpack payload as a single blob under key ``"payload"`` in
the ``"chu_kv"`` namespace, one blob rather than per-dict-key because
``esp32.NVS`` exposes no key enumeration. There is no CRC framing (unlike
the CP NVM path): a corrupt blob is caught when ``unpackb`` rejects it on
load.
"""

__chumicro_runtimes__ = ("micropython",)

import errno

from chumicro_kvstore.core import Backend, KVStoreCorrupt, KVStoreFull

#: ESP-IDF ``ESP_ERR_NVS_NOT_FOUND``: the "key absent" code that
#: ``esp32.NVS`` surfaces via ``OSError`` on a real board (host fakes use
#: ``errno.ENOENT``).
_ESP_ERR_NVS_NOT_FOUND = 0x1102


class MpNvsBackend(Backend):
    """MicroPython ESP32 NVS backend.

    ``nvs`` defaults to ``esp32.NVS("chu_kv")``; tests inject a fake with
    the same ``set_blob`` / ``get_blob`` / ``erase_key`` / ``commit``
    interface. ``capacity`` defaults to 512 B and also sizes the transient
    read buffer allocated at ``load`` time.
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
        try:
            import esp32  # pragma: no cover - MP-ESP32 runtime path
        except ImportError as error:
            raise RuntimeError(
                "MpNvsBackend requires MicroPython ESP32 (esp32.NVS). "
                "On a host, pass `nvs=<fake>` to test the wire format."
            ) from error
        return esp32.NVS(MpNvsBackend.NAMESPACE)  # pragma: no cover - MP-ESP32 runtime path

    def load(self) -> bytes:
        """Return the stored payload, or ``b""`` for a missing key."""
        # Fresh buffer per call: load runs only at construction and reload,
        # so a long-lived bytearray(capacity) would pin RAM for no reuse.
        read_buffer = bytearray(self.capacity)
        try:
            length = self._nvs.get_blob(self.PAYLOAD_KEY, read_buffer)
        except OSError as error:
            code = error.args[0] if error.args else None
            if code in (errno.ENOENT, _ESP_ERR_NVS_NOT_FOUND):
                return b""  # key absent: an empty store, not corruption
            # Any other error means the blob is present but unreadable, so
            # report corruption rather than blank (a blank would overwrite it).
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
