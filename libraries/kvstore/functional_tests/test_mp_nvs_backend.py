"""On-device tests for ``MpNvsBackend`` against real ``esp32.NVS``.

These tests run only on MicroPython ESP32 boards.  Two file-level
markers gate collection:

* ``__chumicro_runtimes__ = ("micropython",)`` — the deploy pipeline
  keeps CP boards out (no ``esp32`` module ever).
* ``__chumicro_features__ = ("esp32",)`` — the pytest-device plugin
  probes each MP target at session start; boards without the
  ``esp32`` module (Pi Pico W on MP) get every item in this file
  deselected before any test runs.

Each test starts by erasing the ``payload`` key in the ``chu_kv``
namespace so prior session state does not leak between tests.
"""

__chumicro_runtimes__ = ("micropython",)
__chumicro_features__ = ("esp32",)

import esp32
from chumicro_kvstore import KVStore
from chumicro_kvstore._backends.mp_nvs import MpNvsBackend


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
    _wipe_nvs()
    backend = MpNvsBackend()
    assert backend.load() == b""


def test_save_then_load_round_trips_on_real_nvs() -> None:
    """Bytes survive a write + read cycle through the real NVS partition."""
    _wipe_nvs()
    backend = MpNvsBackend()
    payload = b"hello from real nvs"
    backend.save(payload)
    assert backend.load() == payload


def test_kvstore_round_trips_through_real_nvs() -> None:
    """Full KVStore lifecycle: commit on board, read back from NVS."""
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
    _wipe_nvs()
    for expected in (1, 2, 3, 4):
        store = KVStore(backend=MpNvsBackend())
        store["boot_count"] = store.get("boot_count", 0) + 1
        assert store.commit_if_changed() is True
        assert store["boot_count"] == expected


def test_commit_if_changed_skips_unchanged_writes() -> None:
    """Wear defense at the substrate level — no NVS commit on no-op."""
    _wipe_nvs()
    store = KVStore(backend=MpNvsBackend())
    store["alpha"] = 1
    assert store.commit_if_changed() is True
    assert store.commit_if_changed() is False  # second call is a no-op


def test_commit_overwrites_previous_payload() -> None:
    """Each commit replaces the prior payload cleanly."""
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
