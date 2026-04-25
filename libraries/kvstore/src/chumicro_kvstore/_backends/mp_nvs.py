"""MicroPython ``esp32.NVS`` backend.

Persists the encoded msgpack payload as a single blob under a fixed
NVS key (``"payload"``) inside the ``"chu_kv"`` namespace.  See
Decision 0034 §6 for why this is single-blob rather than per-dict-key
(short version: MP's ``esp32.NVS`` wrapper does not expose key
enumeration, so per-key storage would require a manifest blob — extra
complexity for marginal wear-leveling gain over the per-namespace
wear leveling NVS already provides).

NVS is wear-leveled and atomic-on-commit at the substrate level, so
the backend skips the CRC framing the CP NVM path needs.

The backend accepts an injected ``nvs`` substrate so host-side tests
can exercise the load / save loop without an ESP32 board — pass any
object that implements ``set_blob(key, value)``, ``get_blob(key,
buffer) -> length``, ``erase_key(key)``, and ``commit()``.
"""

from chumicro_kvstore._backends.base import Backend


class MpNvsBackend(Backend):
    """MP ESP32 NVS backend.

    Args:
        nvs: Optional NVS-shaped substrate (must expose ``set_blob``,
            ``get_blob(key, buffer) -> length``, ``erase_key``, and
            ``commit``).  When ``None`` (default), opens
            ``esp32.NVS("chu_kv")`` — only available under MicroPython
            ESP32 builds.  Tests inject a fake to exercise the wire
            format on a host.
        capacity: Maximum payload size in bytes.  Defaults to 16 KB
            — conservative for the typical ~24 KB NVS partition once
            ESP-IDF metadata overhead is accounted for.  Override on
            boards with custom partition layouts.
    """

    NAMESPACE = "chu_kv"
    PAYLOAD_KEY = "payload"
    DEFAULT_CAPACITY = 16384

    name = "nvs"

    def __init__(self, nvs=None, capacity=None):
        if nvs is None:
            nvs = self._acquire_runtime_nvs()
        self._nvs = nvs
        self.capacity = capacity if capacity is not None else self.DEFAULT_CAPACITY
        # Reusable read buffer — sized to capacity so any committed
        # payload fits in one go.
        self._read_buffer = bytearray(self.capacity)

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
        """Return the stored payload, or ``b""`` if the key is missing.

        NVS raises ``OSError`` (typically ENOENT) on a missing key —
        treated as a blank substrate, no corruption event.
        """
        try:
            length = self._nvs.get_blob(self.PAYLOAD_KEY, self._read_buffer)
        except OSError:
            return b""
        return bytes(self._read_buffer[:length])

    def save(self, payload: bytes) -> None:
        """Write ``payload`` and commit.

        Raises:
            KVStoreFull: ``payload`` exceeds capacity.
        """
        from chumicro_kvstore.core import KVStoreFull

        if len(payload) > self.capacity:
            raise KVStoreFull(
                f"payload size {len(payload)} exceeds NVS capacity {self.capacity}"
            )
        self._nvs.set_blob(self.PAYLOAD_KEY, payload)
        self._nvs.commit()
