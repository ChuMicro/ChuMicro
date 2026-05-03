"""On-device tests for ``MpNvsBackend`` against real ``esp32.NVS``.

These tests run only on MicroPython ESP32 boards.  The module-level
``__chumicro_runtimes__`` marker keeps CP boards out at collection
time; within MP, Pi Pico W has no ``esp32`` module, so every test
early-returns there — the file collects cleanly on any MP device,
but the body only fires on ESP32-class boards.

Each test starts by erasing the ``payload`` key in the ``chu_kv``
namespace so prior session state does not leak between tests.
"""

__chumicro_runtimes__ = ("micropython",)

from chumicro_kvstore import KVStore
from chumicro_kvstore._backends.mp_nvs import MpNvsBackend

try:
    import esp32
    _HAS_ESP32 = True
except ImportError:
    _HAS_ESP32 = False


def _wipe_nvs() -> None:
    """Erase the payload key so each test starts blank."""
    nvs = esp32.NVS(MpNvsBackend.NAMESPACE)
    try:
        nvs.erase_key(MpNvsBackend.PAYLOAD_KEY)
        nvs.commit()
    except OSError:
        # Key didn't exist — fine, already blank.
        pass


def test_blank_nvs_loads_as_empty() -> None:
    """A namespace with no payload key reports empty without raising."""
    if not _HAS_ESP32:
        return
    _wipe_nvs()
    backend = MpNvsBackend()
    assert backend.load() == b""


def test_save_then_load_round_trips_on_real_nvs() -> None:
    """Bytes survive a write + read cycle through the real NVS partition."""
    if not _HAS_ESP32:
        return
    _wipe_nvs()
    backend = MpNvsBackend()
    payload = b"hello from real nvs"
    backend.save(payload)
    assert backend.load() == payload


def test_kvstore_round_trips_through_real_nvs() -> None:
    """Full KVStore lifecycle: commit on board, read back from NVS."""
    if not _HAS_ESP32:
        return
    _wipe_nvs()
    store = KVStore(backend=MpNvsBackend())
    store["boot_count"] = 1
    store["last_seen_ms"] = 12345
    store.commit()

    # Build a fresh KVStore against the same physical NVS namespace
    # and confirm state is recovered — equivalent to a reboot.
    fresh = KVStore(backend=MpNvsBackend())
    assert fresh["boot_count"] == 1
    assert fresh["last_seen_ms"] == 12345


def test_boot_counter_increments_across_fresh_kvstore_instances() -> None:
    """Canonical use case: counter persists across re-construction."""
    if not _HAS_ESP32:
        return
    _wipe_nvs()
    for expected in (1, 2, 3, 4):
        store = KVStore(backend=MpNvsBackend())
        store["boot_count"] = store.get("boot_count", 0) + 1
        assert store.commit_if_changed() is True
        assert store["boot_count"] == expected


def test_commit_if_changed_skips_unchanged_writes() -> None:
    """Wear defense at the substrate level — no NVS commit on no-op."""
    if not _HAS_ESP32:
        return
    _wipe_nvs()
    store = KVStore(backend=MpNvsBackend())
    store["alpha"] = 1
    assert store.commit_if_changed() is True
    assert store.commit_if_changed() is False  # second call is a no-op


def test_commit_overwrites_previous_payload() -> None:
    """Each commit replaces the prior payload cleanly."""
    if not _HAS_ESP32:
        return
    _wipe_nvs()
    store = KVStore(backend=MpNvsBackend())
    store["alpha"] = 1
    store.commit()
    store["alpha"] = 2
    store["beta"] = 99
    store.commit()
    fresh = KVStore(backend=MpNvsBackend())
    assert fresh["alpha"] == 2
    assert fresh["beta"] == 99
