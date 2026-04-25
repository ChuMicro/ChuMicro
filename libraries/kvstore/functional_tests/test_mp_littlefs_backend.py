"""On-device tests for ``MpLittlefsBackend`` against real LittleFS.

Runs anywhere a writable filesystem is mounted — Pi Pico W MP is
the canonical target (no NVS partition, only LittleFS) but ESP32 MP
boards work too if a user explicitly picks
``backend="littlefs"`` instead of the NVS default.

Each test deletes ``/_chu_kv.msgpack`` (and the tmp file) at start
so prior session state doesn't leak between tests.
"""

import sys

from chumicro_kvstore import KVStore
from chumicro_kvstore._backends.mp_littlefs import MpLittlefsBackend

_IS_MICROPYTHON = sys.implementation.name == "micropython"

if _IS_MICROPYTHON:
    import os


def _wipe_payload_file() -> None:
    """Delete the payload + tmp files if they exist."""
    for path in (MpLittlefsBackend.DEFAULT_PATH,
                 MpLittlefsBackend.DEFAULT_PATH + MpLittlefsBackend.TMP_SUFFIX):
        try:
            os.remove(path)
        except OSError:
            pass


def test_blank_filesystem_loads_as_empty() -> None:
    """A filesystem with no payload file reports empty without raising."""
    if not _IS_MICROPYTHON:
        return
    _wipe_payload_file()
    backend = MpLittlefsBackend()
    assert backend.load() == b""


def test_save_then_load_round_trips_on_real_filesystem() -> None:
    """Bytes survive a write + read cycle through the real flash filesystem."""
    if not _IS_MICROPYTHON:
        return
    _wipe_payload_file()
    backend = MpLittlefsBackend()
    payload = b"hello from real littlefs"
    backend.save(payload)
    assert backend.load() == payload


def test_save_uses_atomic_rename_protocol() -> None:
    """Tmp file should not exist after a successful save (rename consumed it)."""
    if not _IS_MICROPYTHON:
        return
    _wipe_payload_file()
    backend = MpLittlefsBackend()
    backend.save(b"check tmp cleanup")
    # After successful save: payload file exists, tmp does not.
    listing = os.listdir("/")
    assert "_chu_kv.msgpack" in listing
    assert "_chu_kv.msgpack.tmp" not in listing


def test_kvstore_round_trips_through_real_filesystem() -> None:
    """Full KVStore lifecycle: commit on board, read back from filesystem."""
    if not _IS_MICROPYTHON:
        return
    _wipe_payload_file()
    store = KVStore(backend=MpLittlefsBackend())
    store["boot_count"] = 1
    store["last_seen_ms"] = 12345
    store.commit()

    fresh = KVStore(backend=MpLittlefsBackend())
    assert fresh["boot_count"] == 1
    assert fresh["last_seen_ms"] == 12345


def test_boot_counter_increments_across_fresh_kvstore_instances() -> None:
    """Canonical use case: counter persists across re-construction."""
    if not _IS_MICROPYTHON:
        return
    _wipe_payload_file()
    for expected in (1, 2, 3, 4):
        store = KVStore(backend=MpLittlefsBackend())
        store["boot_count"] = store.get("boot_count", 0) + 1
        assert store.commit_if_changed() is True
        assert store["boot_count"] == expected


def test_commit_if_changed_skips_unchanged_writes() -> None:
    """Wear defense — identical state ⇒ no rename / sync."""
    if not _IS_MICROPYTHON:
        return
    _wipe_payload_file()
    store = KVStore(backend=MpLittlefsBackend())
    store["alpha"] = 1
    assert store.commit_if_changed() is True
    assert store.commit_if_changed() is False  # second call is a no-op


def test_commit_overwrites_previous_payload() -> None:
    """Each commit replaces the prior payload cleanly."""
    if not _IS_MICROPYTHON:
        return
    _wipe_payload_file()
    store = KVStore(backend=MpLittlefsBackend())
    store["alpha"] = 1
    store.commit()
    store["alpha"] = 2
    store["beta"] = 99
    store.commit()
    fresh = KVStore(backend=MpLittlefsBackend())
    assert fresh["alpha"] == 2
    assert fresh["beta"] == 99
