__chumicro_runtimes__ = ("micropython",)

import errno

from chumicro_kvstore.core import Backend, KVStoreCorrupt, KVStoreFull

# ESP-IDF ESP_ERR_NVS_NOT_FOUND: the "key absent" code esp32.NVS raises (host fakes use errno.ENOENT).
_ESP_ERR_NVS_NOT_FOUND = 0x1102


class MpNvsBackend(Backend):
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
        read_buffer = bytearray(self.capacity)
        try:
            length = self._nvs.get_blob(self.PAYLOAD_KEY, read_buffer)
        except OSError as error:
            code = error.args[0] if error.args else None
            if code in (errno.ENOENT, _ESP_ERR_NVS_NOT_FOUND):
                return b""
            raise KVStoreCorrupt(
                f"NVS read failed for key {self.PAYLOAD_KEY!r} (error {code})",
            ) from error
        return bytes(memoryview(read_buffer)[:length])

    def save(self, payload: bytes) -> None:
        if len(payload) > self.capacity:
            raise KVStoreFull(
                f"payload size {len(payload)} exceeds NVS capacity {self.capacity}"
            )
        self._nvs.set_blob(self.PAYLOAD_KEY, payload)
        self._nvs.commit()
