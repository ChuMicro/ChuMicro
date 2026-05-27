"""Host-side tests for ``CpNvmBackend`` via ``bytearray`` injection.

The backend reads / writes a CRC-framed payload into a contiguous byte
slab.  Real CircuitPython provides ``microcontroller.nvm``; tests
inject a plain ``bytearray`` of any size to exercise the framing
without hardware.

Hardware-side coverage (real ``microcontroller.nvm`` byte slab,
power-cycle behavior) lives under ``functional_tests/``.
"""

#: Host-lane only — exercises a runtime-specific backend through host
#: fakes and asserts off-target behaviour; never staged to a device.
__chumicro_host_only__ = True

import binascii

from chumicro_kvstore import KVStore, KVStoreCorrupt, KVStoreFull
from chumicro_kvstore._backends.cp_nvm import CpNvmBackend
from chumicro_test_harness import raises

# SAMD21 is the small-NVM target: 256 B total minus the 10-byte header
# leaves 246 B payload.
SAMD21_SIZE = 256

# ESP32-class NVM is the large-NVM target: 8 KB.  Tests use a
# convenient mid-sized slab so they're fast.
ESP32_SIZE = 8192


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


def test_capacity_subtracts_header() -> None:
    """``capacity`` always reflects the slab minus the 10-byte header."""
    backend = CpNvmBackend(nvm=bytearray(SAMD21_SIZE))
    assert backend.capacity == SAMD21_SIZE - CpNvmBackend.HEADER_SIZE


def test_capacity_on_esp32_class_slab() -> None:
    backend = CpNvmBackend(nvm=bytearray(ESP32_SIZE))
    assert backend.capacity == ESP32_SIZE - CpNvmBackend.HEADER_SIZE


def test_construction_rejects_too_small_slab() -> None:
    """A slab too small for the header itself raises ``ValueError``."""
    with raises(ValueError):
        CpNvmBackend(nvm=bytearray(8))  # below the 10-byte header


def test_construction_rejects_zero_byte_slab() -> None:
    with raises(ValueError):
        CpNvmBackend(nvm=bytearray(0))


def test_runtime_acquisition_raises_clear_error_on_cpython() -> None:
    """Default-arg construction raises ``RuntimeError`` outside CircuitPython."""
    with raises(RuntimeError):
        CpNvmBackend()  # would try `import microcontroller`


# ---------------------------------------------------------------------------
# Round-trip
# ---------------------------------------------------------------------------


def test_load_blank_0xff_slab_returns_empty() -> None:
    """Raw flash typically erases to 0xFF; the backend reports empty."""
    nvm = bytearray(b"\xff" * SAMD21_SIZE)
    backend = CpNvmBackend(nvm=nvm)
    assert backend.load() == b""


def test_load_blank_0x00_slab_returns_empty() -> None:
    """Some chips initialize NVM to 0x00; backend treats it as blank."""
    nvm = bytearray(SAMD21_SIZE)  # default-init is 0x00
    backend = CpNvmBackend(nvm=nvm)
    assert backend.load() == b""


def test_save_then_load_round_trips() -> None:
    nvm = bytearray(b"\xff" * SAMD21_SIZE)
    backend = CpNvmBackend(nvm=nvm)
    payload = b"\x82\xa3foo\x01\xa3bar\x02"  # msgpack {"foo": 1, "bar": 2}
    backend.save(payload)
    assert backend.load() == payload


def test_save_writes_canonical_header_layout() -> None:
    """Header bytes match the documented frame layout."""
    nvm = bytearray(b"\xff" * SAMD21_SIZE)
    backend = CpNvmBackend(nvm=nvm)
    payload = b"hello world"
    backend.save(payload)
    assert bytes(nvm[0:4]) == b"CKVS"
    assert int.from_bytes(bytes(nvm[4:6]), "little") == len(payload)
    expected_crc = binascii.crc32(payload) & 0xFFFFFFFF
    assert int.from_bytes(bytes(nvm[6:10]), "little") == expected_crc
    assert bytes(nvm[10 : 10 + len(payload)]) == payload


def test_save_overwrites_previous_payload() -> None:
    nvm = bytearray(b"\xff" * SAMD21_SIZE)
    backend = CpNvmBackend(nvm=nvm)
    backend.save(b"first")
    backend.save(b"second-and-longer")
    assert backend.load() == b"second-and-longer"


# ---------------------------------------------------------------------------
# Capacity enforcement
# ---------------------------------------------------------------------------


def test_save_raises_kvstorefull_when_payload_exceeds_capacity() -> None:
    nvm = bytearray(b"\xff" * SAMD21_SIZE)
    backend = CpNvmBackend(nvm=nvm)
    too_big = b"x" * (backend.capacity + 1)
    with raises(KVStoreFull):
        backend.save(too_big)


def test_save_at_exact_capacity_succeeds() -> None:
    nvm = bytearray(b"\xff" * SAMD21_SIZE)
    backend = CpNvmBackend(nvm=nvm)
    edge = b"x" * backend.capacity
    backend.save(edge)
    assert backend.load() == edge


# ---------------------------------------------------------------------------
# Corruption detection
# ---------------------------------------------------------------------------


def test_load_raises_on_bad_magic() -> None:
    """A non-blank slab with a bad magic raises ``KVStoreCorrupt``.

    Bytes that are neither ``b"CKVS"`` nor a uniform 0xFF/0x00 fill
    indicate the slab was written by something else — a different
    framing format, a foreign app, or genuinely corrupted bytes.
    """
    nvm = bytearray(b"\xff" * SAMD21_SIZE)
    nvm[0:4] = b"XXXX"
    backend = CpNvmBackend(nvm=nvm)
    with raises(KVStoreCorrupt):
        backend.load()


def test_load_raises_on_length_exceeds_capacity() -> None:
    """A length field claiming more bytes than the slab holds is corrupt."""
    nvm = bytearray(b"\xff" * SAMD21_SIZE)
    nvm[0:4] = b"CKVS"
    nvm[4:6] = (SAMD21_SIZE + 1).to_bytes(2, "little")
    nvm[6:10] = (0).to_bytes(4, "little")
    backend = CpNvmBackend(nvm=nvm)
    with raises(KVStoreCorrupt):
        backend.load()


def test_load_raises_on_crc_mismatch() -> None:
    """A flipped payload byte after a successful save trips the CRC check."""
    nvm = bytearray(b"\xff" * SAMD21_SIZE)
    backend = CpNvmBackend(nvm=nvm)
    backend.save(b"hello world")
    # Flip a payload byte without updating the CRC field.
    nvm[CpNvmBackend.HEADER_SIZE] ^= 0x01
    with raises(KVStoreCorrupt):
        backend.load()


def test_load_raises_on_zero_length_with_wrong_crc() -> None:
    """Empty payload with a non-zero CRC field is also corruption."""
    nvm = bytearray(b"\xff" * SAMD21_SIZE)
    nvm[0:4] = b"CKVS"
    nvm[4:6] = (0).to_bytes(2, "little")
    nvm[6:10] = (0xDEADBEEF).to_bytes(4, "little")
    backend = CpNvmBackend(nvm=nvm)
    with raises(KVStoreCorrupt):
        backend.load()


def test_load_zero_length_with_zero_crc_succeeds() -> None:
    """Empty payload with a CRC of zero matches an empty msgpack: valid."""
    nvm = bytearray(b"\xff" * SAMD21_SIZE)
    nvm[0:4] = b"CKVS"
    nvm[4:6] = (0).to_bytes(2, "little")
    nvm[6:10] = (binascii.crc32(b"") & 0xFFFFFFFF).to_bytes(4, "little")
    backend = CpNvmBackend(nvm=nvm)
    assert backend.load() == b""


# ---------------------------------------------------------------------------
# Integration through KVStore
# ---------------------------------------------------------------------------


def test_kvstore_with_cp_nvm_backend_round_trips_through_reload() -> None:
    """Full vertical: KVStore through CpNvmBackend, a bytearray
    substrate, and back via reload.
    """
    nvm = bytearray(b"\xff" * SAMD21_SIZE)
    backend = CpNvmBackend(nvm=nvm)
    store = KVStore(backend=backend)
    store["boot_count"] = 7
    store["last_seen_ms"] = 42
    store.commit()
    # Drop in-memory state, reread from the same NVM substrate.
    store["boot_count"] = 999
    store.reload()
    assert store["boot_count"] == 7
    assert store["last_seen_ms"] == 42


def test_kvstore_with_cp_nvm_backend_construction_handles_blank_nvm() -> None:
    """Auto-load on a blank slab produces an empty store, no corruption."""
    nvm = bytearray(b"\xff" * SAMD21_SIZE)
    backend = CpNvmBackend(nvm=nvm)
    store = KVStore(backend=backend)
    assert len(store) == 0
    assert store.is_corrupt is False


def test_kvstore_with_cp_nvm_backend_construction_handles_corruption_silently() -> None:
    """A corrupt slab surfaces via ``is_corrupt`` and resets the store."""
    nvm = bytearray(b"\xff" * SAMD21_SIZE)
    nvm[0:4] = b"XXXX"
    backend = CpNvmBackend(nvm=nvm)
    store = KVStore(backend=backend)
    assert store.is_corrupt is True
    assert len(store) == 0


def test_kvstore_with_cp_nvm_backend_commit_clears_corruption() -> None:
    """A successful commit overwrites the corrupt slab cleanly."""
    nvm = bytearray(b"\xff" * SAMD21_SIZE)
    nvm[0:4] = b"XXXX"
    backend = CpNvmBackend(nvm=nvm)
    store = KVStore(backend=backend)
    assert store.is_corrupt is True
    store["alpha"] = 1
    store.commit()
    assert store.is_corrupt is False
    # Build a fresh store against the same substrate to confirm the
    # post-commit slab decodes cleanly.
    fresh = KVStore(backend=CpNvmBackend(nvm=nvm))
    assert fresh["alpha"] == 1
