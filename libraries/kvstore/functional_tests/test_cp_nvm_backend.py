"""On-device tests for ``CpNvmBackend`` against real ``microcontroller.nvm``.

These tests run only on CircuitPython boards.  The module-level
``__chumicro_runtimes__`` marker tells the pytest-device plugin to
skip the wrong-runtime parametrization, so MP boards don't even try
to import the file.

Each test resets NVM to ``0xFF`` (the erased-flash state) before
running so prior session state does not leak between tests.
"""

__chumicro_runtimes__ = ("circuitpython",)

import microcontroller
from chumicro_kvstore import KVStore, KVStoreCorrupt
from chumicro_kvstore._backends.cp_nvm import CpNvmBackend
from chumicro_test_harness.assertions import raises


def _wipe_nvm() -> None:
    """Reset the entire NVM slab to ``0xFF`` (erased-flash state)."""
    microcontroller.nvm[:] = b"\xff" * len(microcontroller.nvm)


def test_blank_nvm_after_wipe_loads_as_empty() -> None:
    """A wiped slab decodes as empty without raising."""
    _wipe_nvm()
    backend = CpNvmBackend()
    assert backend.load() == b""


def test_save_then_load_round_trips_on_real_nvm() -> None:
    """Bytes survive a write + read cycle through the real flash slab."""
    _wipe_nvm()
    backend = CpNvmBackend()
    payload = b"hello from real nvm"
    backend.save(payload)
    assert backend.load() == payload


def test_capacity_matches_board_nvm_minus_header() -> None:
    """Capacity reflects the live NVM size minus the 10-byte header.

    Board NVM size is fixed in CircuitPython's ``mpconfigport.h`` —
    e.g. 8 KB on ESP32, 4 KB on RP2040, 256 B on SAMD21.  The library
    derives capacity from ``len(microcontroller.nvm)`` so a future CP
    release that grows the slab is picked up automatically.
    """
    backend = CpNvmBackend()
    assert backend.capacity == len(microcontroller.nvm) - CpNvmBackend.HEADER_SIZE


def test_kvstore_round_trips_through_real_nvm() -> None:
    """Full KVStore lifecycle: commit on board, read back from NVM."""
    _wipe_nvm()
    store = KVStore(backend=CpNvmBackend())
    store["boot_count"] = 1
    store["last_seen_ms"] = 12345
    store.commit()

    # Build a fresh KVStore against the same physical NVM and confirm
    # state is recovered — equivalent to a reboot on this slice.
    fresh = KVStore(backend=CpNvmBackend())
    assert fresh["boot_count"] == 1
    assert fresh["last_seen_ms"] == 12345


def test_corruption_detected_on_tampered_nvm() -> None:
    """Flipping a payload byte trips the CRC check on next load."""
    _wipe_nvm()
    backend = CpNvmBackend()
    backend.save(b"valid payload")
    # Flip a payload byte without updating the CRC field.
    tampered = microcontroller.nvm[CpNvmBackend.HEADER_SIZE] ^ 0x01
    microcontroller.nvm[CpNvmBackend.HEADER_SIZE : CpNvmBackend.HEADER_SIZE + 1] = bytes([tampered])
    with raises(KVStoreCorrupt):
        backend.load()
    _wipe_nvm()  # leave clean for the next test


def test_kvstore_construction_handles_corruption_silently() -> None:
    """Auto-load on a corrupt slab surfaces ``is_corrupt``, no exception."""
    _wipe_nvm()
    microcontroller.nvm[0:4] = b"XXXX"
    store = KVStore(backend=CpNvmBackend())
    assert store.is_corrupt is True
    assert len(store) == 0
    _wipe_nvm()


def test_boot_counter_increments_across_fresh_kvstore_instances() -> None:
    """Boot-counter pattern: counter survives a fresh KVStore.

    A future hard-reset suite will exercise across an actual reboot;
    this test proves the substrate works across re-construction (the
    same code path the boot path takes after a reboot).
    """
    _wipe_nvm()

    for expected in (1, 2, 3, 4):
        store = KVStore(backend=CpNvmBackend())
        store["boot_count"] = store.get("boot_count", 0) + 1
        assert store.commit_if_changed() is True
        assert store["boot_count"] == expected


def test_commit_if_changed_skips_unchanged_writes_on_real_flash() -> None:
    """Wear defense: identical state means no flash write.

    Side-effect test: the slab bytes after the second call are
    identical to the bytes after the first.  If an actual write
    happened we'd see a fresh CRC computed over the same data
    (unchanged) but the test confirms the flash bytes don't churn
    — the no-op early-return is what saves cycles.
    """
    _wipe_nvm()
    store = KVStore(backend=CpNvmBackend())
    store["alpha"] = 1
    assert store.commit_if_changed() is True
    snapshot = bytes(microcontroller.nvm[: CpNvmBackend.HEADER_SIZE + 32])
    assert store.commit_if_changed() is False
    assert bytes(microcontroller.nvm[: CpNvmBackend.HEADER_SIZE + 32]) == snapshot
