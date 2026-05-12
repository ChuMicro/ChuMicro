"""CircuitPython ``microcontroller.nvm`` backend with CRC framing.

Persists a single msgpack payload into the NVM byte slab, prefixed
with magic header + CRC32 for power-loss-corruption detection::

    offset 0:  4 bytes — MAGIC b"CKVS"
    offset 4:  2 bytes — LEN (little-endian uint16)
    offset 6:  4 bytes — CRC32 (little-endian uint32, IEEE polynomial)
    offset 10: LEN bytes — MSGPACK payload

A blank slab (all ``0xFF`` from raw flash erase, or all ``0x00`` on
some chips) is treated as "no state yet" and reports ``is_corrupt =
False, bytes_used = 0``.  Bad magic raises ``KVStoreCorrupt``.

Tests inject a ``bytearray`` ``nvm`` substrate to exercise the full
framing without a CircuitPython runtime.
"""

__chumicro_runtimes__ = ("circuitpython",)

import binascii

from chumicro_kvstore.core import Backend, KVStoreCorrupt, KVStoreFull


class CpNvmBackend(Backend):
    """CircuitPython NVM backend.

    ``nvm`` defaults to the live ``microcontroller.nvm`` byte slab;
    tests inject a plain ``bytearray`` to exercise the framing on a
    host without hardware.
    """

    HEADER_MAGIC = b"CKVS"
    HEADER_SIZE = 10  # MAGIC(4) + LEN(2) + CRC32(4)

    name = "nvm"

    def __init__(self, nvm: bytearray | None = None) -> None:
        if nvm is None:
            nvm = self._acquire_runtime_nvm()
        if len(nvm) <= self.HEADER_SIZE:
            raise ValueError(
                f"NVM is too small ({len(nvm)} bytes) for the {self.HEADER_SIZE}-byte header."
            )
        self._nvm = nvm
        self.capacity = len(nvm) - self.HEADER_SIZE

    @staticmethod
    def _acquire_runtime_nvm() -> bytearray:
        """Return ``microcontroller.nvm`` or raise a clear error.

        The wrapper exists so the CPython-side error is informative
        rather than a bare ``ImportError`` from ``microcontroller``.
        """
        try:
            import microcontroller  # pragma: no cover - CP runtime path
        except ImportError as error:
            raise RuntimeError(
                "CpNvmBackend requires CircuitPython (microcontroller.nvm). "
                "On a host, pass `nvm=bytearray(<size>)` to test the framing."
            ) from error
        return microcontroller.nvm  # pragma: no cover - CP runtime path

    def load(self) -> bytes:
        """Read the framed payload from NVM.

        Returns:
            The msgpack payload bytes, or ``b""`` for a blank slab.

        Raises:
            KVStoreCorrupt: Magic, length, or CRC failed validation.
        """
        # Blank slab — raw flash typically erases to 0xFF and some chips
        # init to 0x00; either pattern in the magic position means "never
        # written" rather than corrupted.
        magic = bytes(self._nvm[0 : len(self.HEADER_MAGIC)])
        if magic in (b"\xff\xff\xff\xff", b"\x00\x00\x00\x00"):
            return b""
        if magic != self.HEADER_MAGIC:
            raise KVStoreCorrupt(f"NVM magic mismatch: got {magic!r}")

        length = int.from_bytes(self._nvm[4:6], "little")
        if length > self.capacity:
            raise KVStoreCorrupt(
                f"NVM length field {length} exceeds capacity {self.capacity}"
            )

        stored_crc = int.from_bytes(self._nvm[6:10], "little")
        payload = bytes(self._nvm[self.HEADER_SIZE : self.HEADER_SIZE + length])
        actual_crc = binascii.crc32(payload) & 0xFFFFFFFF
        if actual_crc != stored_crc:
            raise KVStoreCorrupt(
                f"NVM CRC mismatch: stored 0x{stored_crc:08x}, computed 0x{actual_crc:08x}"
            )
        return payload

    def save(self, payload: bytes) -> None:
        """Write the framed payload into NVM.

        Raises:
            KVStoreFull: Payload exceeds capacity.
        """
        if len(payload) > self.capacity:
            raise KVStoreFull(
                f"payload size {len(payload)} exceeds NVM capacity {self.capacity}"
            )

        crc = binascii.crc32(payload) & 0xFFFFFFFF
        header = (
            self.HEADER_MAGIC
            + len(payload).to_bytes(2, "little")
            + crc.to_bytes(4, "little")
        )
        # Write header + payload as a single contiguous span.  CP's
        # ByteArray slice-assignment commits to NVM atomically per slice;
        # on raw bytearray (host tests) it's a plain memory write.
        self._nvm[0 : self.HEADER_SIZE] = header
        self._nvm[self.HEADER_SIZE : self.HEADER_SIZE + len(payload)] = payload
