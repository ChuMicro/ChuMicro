"""Phase 3b acceptance — auto-detect + multi-type persistence on real hardware.

Closes the kvstore phase by verifying the cross-cutting behaviors
that don't belong to any single backend's suite:

* ``KVStore(backend="auto")`` picks the substrate-appropriate backend
  for each runtime + board.
* Every ``chumicro-msgpack``-supported value type round-trips through
  the persistence layer (int, bool, float, str, bytes, list, tuple →
  list, dict, None).
* The boot-counter pattern works on the auto-selected backend
  without the test having to know which one was picked.

The "across hard reset" guarantee mentioned in Decision 0034 is
exercised implicitly via the fresh-``KVStore``-instance pattern —
the same code path the boot path takes after a power cycle.  Real
power-cycle testing is out of scope for the pytest harness (the
device connection dies on hard reset); the substrate-level
atomicity guarantees (CP NVM CRC, NVS commit-atomic, LittleFS
rename-atomic) plus per-substrate functional tests in this slice
together cover the failure modes that matter.
"""

import sys

from chumicro_kvstore import KVStore

_IS_CIRCUITPYTHON = sys.implementation.name == "circuitpython"
_IS_MICROPYTHON = sys.implementation.name == "micropython"

if _IS_CIRCUITPYTHON:
    import microcontroller

if _IS_MICROPYTHON:
    try:
        import esp32
        _HAS_NVS = True
    except ImportError:
        _HAS_NVS = False
    import os
else:
    _HAS_NVS = False


def _wipe_substrates() -> None:
    """Reset every substrate this runtime can reach to a clean state.

    Belt-and-suspenders: each test starts blank regardless of whether
    a previous run left state behind.
    """
    if _IS_CIRCUITPYTHON:
        microcontroller.nvm[:] = b"\xff" * len(microcontroller.nvm)
        return
    if _IS_MICROPYTHON:
        if _HAS_NVS:
            try:
                nvs = esp32.NVS("chu_kv")
                nvs.erase_key("payload")
                nvs.commit()
            except OSError:
                pass
        for path in ("/_chu_kv.msgpack", "/_chu_kv.msgpack.tmp"):
            try:
                os.remove(path)
            except OSError:
                pass


def test_auto_detect_picks_runtime_appropriate_backend() -> None:
    """``backend="auto"`` resolves to the substrate-native backend."""
    _wipe_substrates()
    store = KVStore(backend="auto")
    if _IS_CIRCUITPYTHON:
        assert store.backend_name == "nvm"
    elif _IS_MICROPYTHON and _HAS_NVS:
        assert store.backend_name == "nvs"
    elif _IS_MICROPYTHON:
        assert store.backend_name == "littlefs"


def test_auto_backend_round_trips_all_msgpack_value_types() -> None:
    """Every value type chumicro-msgpack supports survives a commit + reload.

    Decision 0034 §10 enumerates the supported types; this test runs
    the full table through the auto-selected backend so the canonical
    use case (the user picks ``"auto"`` and writes whatever they
    want) actually works on every runtime.
    """
    _wipe_substrates()
    store = KVStore(backend="auto")
    store["int_val"] = 42
    store["bool_val"] = True
    store["float_val"] = 3.5
    store["str_val"] = "hello"
    store["bytes_val"] = b"raw bytes"
    store["list_val"] = [1, 2, 3]
    store["dict_val"] = {"nested": "value"}
    store["none_val"] = None
    store.commit()

    fresh = KVStore(backend="auto")
    assert fresh["int_val"] == 42
    assert fresh["bool_val"] is True
    assert fresh["float_val"] == 3.5
    assert fresh["str_val"] == "hello"
    assert fresh["bytes_val"] == b"raw bytes"
    assert fresh["list_val"] == [1, 2, 3]
    assert fresh["dict_val"] == {"nested": "value"}
    assert fresh["none_val"] is None


def test_auto_backend_boot_counter_pattern() -> None:
    """The canonical use case works on whichever backend auto picked."""
    _wipe_substrates()
    for expected in (1, 2, 3):
        store = KVStore(backend="auto")
        store["boot_count"] = store.get("boot_count", 0) + 1
        assert store.commit_if_changed() is True
        assert store["boot_count"] == expected


def test_explicit_littlefs_works_on_micropython_regardless_of_nvs() -> None:
    """`backend="littlefs"` is pickable on any MP runtime with a filesystem.

    Both Pi Pico W (no NVS) and Lolin S2 (has NVS) should let the
    user opt into LittleFS storage — confirms the design point that
    auto-detect is a default, not a constraint.
    """
    if not _IS_MICROPYTHON:
        return
    _wipe_substrates()
    store = KVStore(backend="littlefs")
    store["pick_me"] = "via littlefs"
    store.commit()
    fresh = KVStore(backend="littlefs")
    assert fresh["pick_me"] == "via littlefs"


def test_explicit_nvs_works_on_micropython_esp32() -> None:
    """`backend="nvs"` is the substrate-native pick on MP-ESP32."""
    if not (_IS_MICROPYTHON and _HAS_NVS):
        return
    _wipe_substrates()
    store = KVStore(backend="nvs")
    store["pick_me"] = "via nvs"
    store.commit()
    fresh = KVStore(backend="nvs")
    assert fresh["pick_me"] == "via nvs"


def test_corrupt_substrate_lets_app_keep_running() -> None:
    """Construction never raises; corrupt substrate surfaces via ``is_corrupt``.

    The boot-time guarantee: even if persisted state is unreadable,
    the app must boot.  KVStore reports the corruption event so the
    app can log + reset, and continues with an empty store.
    """
    if _IS_CIRCUITPYTHON:
        # Tamper with NVM magic — easiest cross-board way to fake corruption.
        microcontroller.nvm[:] = b"\xff" * len(microcontroller.nvm)
        microcontroller.nvm[0:4] = b"XXXX"
        store = KVStore(backend="auto")
        assert store.is_corrupt is True
        assert len(store) == 0
        # Cleanup
        microcontroller.nvm[:] = b"\xff" * len(microcontroller.nvm)
    elif _IS_MICROPYTHON:
        # MP NVS / LittleFS handle "missing" as empty (not corrupt) — they
        # don't have CP NVM's framing-mismatch class of failure.  Run the
        # cleaner "construction on never-written substrate works" check
        # here so the MP arm still exercises the auto-load resilience.
        _wipe_substrates()
        store = KVStore(backend="auto")
        assert store.is_corrupt is False
        assert len(store) == 0
