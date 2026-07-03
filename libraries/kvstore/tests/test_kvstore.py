"""Host-side tests for ``chumicro-kvstore`` against the memory backend.

Cross-runtime compatible: runs under CPython pytest, and under
MicroPython + CircuitPython unix-ports via ``pytest libraries/kvstore/
tests --target unix-port`` (the ``chumicro-pytest-device`` plugin's
unix-port backend).  Only ``MemoryBackend`` is exercised here; the
per-runtime backends have their own functional-test suites under
``functional_tests/``.
"""

import sys

from chumicro_kvstore import (
    KVStore,
    KVStoreCorrupt,
    KVStoreError,
    KVStoreFull,
)
from chumicro_kvstore._backends.memory import MemoryBackend
from chumicro_kvstore.testing import FakeKVStore
from chumicro_test_harness import raises, skip

# ---------------------------------------------------------------------------
# Construction + auto-detect
# ---------------------------------------------------------------------------


def test_default_backend_is_memory_on_cpython() -> None:
    """``backend="auto"`` resolves to MemoryBackend under CPython.

    Runtime-aware: under MP and CP unix-port the auto-detect path
    routes to the per-runtime backends (which are still stubs in this
    slice).  Their selection logic is exercised by the functional
    suites. Assert the CPython case here only.
    """
    if sys.implementation.name != "cpython":
        skip("auto-detect on MP/CP unix-port is covered by the functional suites")
    store = KVStore(backend="auto")
    assert store.backend_name == "memory"


def test_explicit_memory_backend() -> None:
    """``backend="memory"`` is always available."""
    store = KVStore(backend="memory")
    assert store.backend_name == "memory"


def test_unknown_backend_raises() -> None:
    """Unknown backend strings raise ``ValueError`` with a clear message."""
    with raises(ValueError):
        KVStore(backend="bogus")


def test_concrete_backend_instance_accepted() -> None:
    """A pre-built backend instance bypasses string resolution."""
    backend = MemoryBackend(capacity=512)
    store = KVStore(backend=backend)
    assert store.backend_name == "memory"
    assert store.capacity == 512


# ---------------------------------------------------------------------------
# Mapping-style API
# ---------------------------------------------------------------------------


def test_set_get_delete() -> None:
    """Basic dict-style read/write/delete cycle."""
    store = KVStore(backend="memory")
    store["boot_count"] = 1
    assert store["boot_count"] == 1
    del store["boot_count"]
    assert "boot_count" not in store


def test_get_with_default() -> None:
    """``get`` returns the default for missing keys."""
    store = KVStore(backend="memory")
    assert store.get("missing", 7) == 7


def test_contains_and_len() -> None:
    """``in`` and ``len`` track the in-memory dict."""
    store = KVStore(backend="memory")
    assert len(store) == 0
    store["a"] = 1
    store["b"] = 2
    assert len(store) == 2
    assert "a" in store
    assert "missing" not in store


def test_iter_yields_keys() -> None:
    """``for key in store`` yields the dict's keys."""
    store = KVStore(backend="memory")
    store["alpha"] = 1
    store["beta"] = 2
    assert sorted(store) == ["alpha", "beta"]


def test_keys_items_values() -> None:
    """The three view methods mirror the dict's contents."""
    store = KVStore(backend="memory")
    store["alpha"] = 1
    store["beta"] = 2
    assert sorted(store.keys()) == ["alpha", "beta"]
    assert sorted(store.values()) == [1, 2]
    assert sorted(store.items()) == [("alpha", 1), ("beta", 2)]


def test_pop_with_default() -> None:
    """``pop`` returns + removes a key, falling back to *default*."""
    store = KVStore(backend="memory")
    store["alpha"] = 1
    assert store.pop("alpha") == 1
    assert "alpha" not in store
    assert store.pop("missing", 99) == 99


def test_pop_missing_no_default_raises() -> None:
    """``pop`` without *default* raises ``KeyError`` on missing keys."""
    store = KVStore(backend="memory")
    with raises(KeyError):
        store.pop("missing")


def test_clear_empties_dict_without_committing() -> None:
    """``clear`` wipes in-memory state; backend is untouched until commit."""
    store = KVStore(backend="memory")
    store["alpha"] = 1
    store.commit()
    store.clear()
    assert len(store) == 0
    # Backend still has the pre-clear payload until the next commit.
    store.reload()
    assert store["alpha"] == 1


def test_update_merges() -> None:
    """``update`` merges another dict into the in-memory state."""
    store = KVStore(backend="memory")
    store["alpha"] = 1
    store.update({"beta": 2, "gamma": 3})
    assert store["beta"] == 2
    assert store["gamma"] == 3
    assert store["alpha"] == 1


# ---------------------------------------------------------------------------
# Lifecycle: commit / commit_if_changed / reload
# ---------------------------------------------------------------------------


def test_commit_persists_through_reload() -> None:
    """A committed store round-trips through ``reload``."""
    store = KVStore(backend="memory")
    store["boot_count"] = 7
    store["last_seen_ms"] = 12345
    store.commit()
    store["boot_count"] = 999  # not yet committed
    store.reload()
    assert store["boot_count"] == 7
    assert store["last_seen_ms"] == 12345


def test_commit_if_changed_skips_unchanged() -> None:
    """Repeated ``commit_if_changed`` returns ``False`` when state is stable."""
    store = KVStore(backend="memory")
    store["alpha"] = 1
    assert store.commit_if_changed() is True
    assert store.commit_if_changed() is False
    assert store.commit_if_changed() is False


def test_commit_if_changed_writes_when_changed() -> None:
    """``commit_if_changed`` returns ``True`` after a real mutation."""
    store = KVStore(backend="memory")
    store["alpha"] = 1
    store.commit()
    store["alpha"] = 2
    assert store.commit_if_changed() is True


def test_commit_if_changed_does_not_encode_when_clean() -> None:
    """A clean store skips the encode entirely (no allocation on the
    every-tick no-change path the guide recommends)."""
    store = KVStore(backend="memory")
    store["alpha"] = 1
    store.commit()
    # Sabotage packb so any encode attempt is loud; a clean store must
    # not call it.
    import chumicro_kvstore.core as core_mod

    original = core_mod.packb
    core_mod.packb = lambda _data: (_ for _ in ()).throw(
        AssertionError("commit_if_changed encoded a clean store"),
    )
    try:
        assert store.commit_if_changed() is False
    finally:
        core_mod.packb = original


def test_commit_rejects_undecodable_deep_nesting() -> None:
    """commit() refuses a value too deeply nested for the decoder, so the
    store never persists bytes it can't read back on the next load."""
    store = KVStore(backend="memory")
    deep = 0
    for _ in range(9):  # past msgpack _MAX_DEPTH (8)
        deep = [deep]
    store["deep"] = deep
    with raises(ValueError):
        store.commit()


def test_commit_allowed_when_backend_capacity_is_zero_sentinel() -> None:
    """A custom backend that only implements load/save (leaving the base
    capacity default 0 = unbounded) accepts commits rather than rejecting
    even a 1-byte empty-dict payload."""
    from chumicro_kvstore.core import Backend

    class _MinimalBackend(Backend):
        name = "minimal"

        def __init__(self):
            self._payload = b""

        def load(self):
            return self._payload

        def save(self, payload):
            self._payload = bytes(payload)

    store = KVStore(backend=_MinimalBackend())
    assert store.capacity == 0
    store["k"] = 1
    store.commit()  # must not raise KVStoreFull from the zero-cap default
    assert store.commit_if_changed() is False


def test_reload_picks_up_external_payload() -> None:
    """Backend payload set externally is visible after ``reload``."""
    backend = MemoryBackend()
    store = KVStore(backend=backend)
    store["seed"] = 1
    store.commit()
    seeded_payload = backend._payload  # noqa: SLF001 - test introspection
    other_store = KVStore(backend=MemoryBackend(initial=seeded_payload))
    assert other_store["seed"] == 1


# ---------------------------------------------------------------------------
# Capacity + KVStoreFull
# ---------------------------------------------------------------------------


def test_commit_raises_kvstorefull_when_payload_too_large() -> None:
    """``commit`` raises ``KVStoreFull`` past the capacity threshold."""
    backend = MemoryBackend(capacity=4)  # tiny on purpose
    store = KVStore(backend=backend)
    store["k"] = "this string is far longer than four bytes"
    with raises(KVStoreFull):
        store.commit()


def test_commit_if_changed_raises_kvstorefull() -> None:
    """The wear-aware commit path also enforces capacity."""
    backend = MemoryBackend(capacity=4)
    store = KVStore(backend=backend)
    store["k"] = "x" * 100
    with raises(KVStoreFull):
        store.commit_if_changed()


def test_capacity_property_reflects_backend() -> None:
    """``store.capacity`` mirrors the active backend's capacity."""
    store = KVStore(backend=MemoryBackend(capacity=128))
    assert store.capacity == 128


def test_bytes_used_grows_with_payload() -> None:
    """``bytes_used`` tracks the encoded size of the in-memory dict."""
    store = KVStore(backend="memory")
    baseline = store.bytes_used
    store["alpha"] = 1
    assert store.bytes_used > baseline


# ---------------------------------------------------------------------------
# Corruption semantics
# ---------------------------------------------------------------------------


def test_construction_with_corrupt_payload_resets_silently() -> None:
    """Construction never raises on corrupt; ``is_corrupt`` surfaces it."""
    backend = MemoryBackend(initial=b"not msgpack at all")
    store = KVStore(backend=backend)
    assert store.is_corrupt is True
    assert len(store) == 0


def test_reload_raises_on_non_dict_payload() -> None:
    """``reload`` raises ``KVStoreCorrupt`` when the payload decodes to a non-dict.

    Construction-time auto-load resets to empty silently; ``reload``
    is the explicit form callers use to surface the exception.
    """
    backend = MemoryBackend()
    backend._payload = b"\xc3"  # noqa: SLF001 - msgpack-encoded `True`, decodes to bool
    store = KVStore(backend=MemoryBackend())  # start clean
    store._backend = backend  # noqa: SLF001 - swap to the bad backend for reload
    with raises(KVStoreCorrupt):
        store.reload()


def test_construction_with_truncated_msgpack_resets_silently() -> None:
    """A power-loss-truncated payload (unpackb raises) is corruption, not a boot crash."""
    # bin8 claiming 200 bytes, only 2 supplied — unpackb raises ValueError.
    store = KVStore(backend=MemoryBackend(initial=b"\xc4\xc8\x01\x02"))
    assert store.is_corrupt is True
    assert len(store) == 0


def test_reload_raises_on_malformed_msgpack() -> None:
    """``reload`` surfaces a malformed-framing decode failure as ``KVStoreCorrupt``."""
    store = KVStore(backend=MemoryBackend())  # start clean
    store._backend = MemoryBackend(  # noqa: SLF001 - swap to the bad backend
        initial=b"\xc4\xc8\x01\x02",
    )
    with raises(KVStoreCorrupt):
        store.reload()


def test_commit_clears_is_corrupt() -> None:
    """A successful ``commit`` clears the sticky corruption flag."""
    backend = MemoryBackend(initial=b"junk")
    store = KVStore(backend=backend)
    assert store.is_corrupt is True
    store["alpha"] = 1
    store.commit()
    assert store.is_corrupt is False


def test_simulated_backend_corruption_raises_on_explicit_reload() -> None:
    """``MemoryBackend.force_corrupt`` makes the next load raise."""
    backend = MemoryBackend()
    store = KVStore(backend=backend)
    store["alpha"] = 1
    store.commit()
    backend.force_corrupt()
    with raises(KVStoreCorrupt):
        store.reload()


def test_construction_with_corrupt_backend_load_resets_silently() -> None:
    """``KVStoreCorrupt`` raised during auto-load is caught silently.

    Exercises the construction-path branch where the backend itself
    (not the msgpack decoder) flags corruption. The
    ``MemoryBackend.force_corrupt`` test hook stands in for CP NVM's
    real CRC-mismatch failure mode.
    """
    backend = MemoryBackend()
    backend.force_corrupt()
    store = KVStore(backend=backend)
    assert store.is_corrupt is True
    assert len(store) == 0


def test_reload_against_empty_backend_resets_to_empty() -> None:
    """Reloading from a wiped backend returns the store to empty cleanly.

    Exercises the empty-payload short-circuit inside ``reload``.
    """
    backend = MemoryBackend()
    store = KVStore(backend=backend)
    store["alpha"] = 1
    # Backend never had `commit` called, so its payload is still b"".
    store.reload()
    assert len(store) == 0
    assert store.is_corrupt is False


# ---------------------------------------------------------------------------
# Exception hierarchy
# ---------------------------------------------------------------------------


def test_kvstore_full_inherits_kvstore_error() -> None:
    """Catching ``KVStoreError`` catches every sub-exception."""
    assert issubclass(KVStoreFull, KVStoreError)
    assert issubclass(KVStoreCorrupt, KVStoreError)


# ---------------------------------------------------------------------------
# FakeKVStore — round-trip the same code paths production hits
# ---------------------------------------------------------------------------


def test_fake_kvstore_works_as_kvstore() -> None:
    """``FakeKVStore`` is a drop-in for tests that need a real KVStore."""
    fake = FakeKVStore()
    fake["alpha"] = 1
    fake.commit()
    fake.reload()
    assert fake["alpha"] == 1


def test_fake_kvstore_capacity_override() -> None:
    """The ``capacity=`` constructor arg drives ``KVStoreFull``."""
    fake = FakeKVStore(capacity=8)
    fake["k"] = "x" * 100
    with raises(KVStoreFull):
        fake.commit()


def test_fake_kvstore_records_calls_when_enabled() -> None:
    """``record_calls=True`` captures every public-API call for assertion."""
    fake = FakeKVStore(record_calls=True)
    fake["alpha"] = 1
    fake.commit()
    fake["beta"] = 2
    fake.commit_if_changed()
    assert ("__setitem__", ("alpha", 1)) in fake.calls
    assert ("commit", ()) in fake.calls
    assert ("commit_if_changed", ()) in fake.calls


def test_fake_kvstore_simulate_corrupt() -> None:
    """``simulate_corrupt`` drives the corruption path deterministically."""
    fake = FakeKVStore()
    fake["alpha"] = 1
    fake.commit()
    fake.simulate_corrupt()
    with raises(KVStoreCorrupt):
        fake.reload()


def test_fake_kvstore_set_capacity_at_runtime() -> None:
    """Tests can shrink capacity mid-test to drive ``KVStoreFull``."""
    fake = FakeKVStore()
    fake["alpha"] = 1
    fake.commit()  # fits at sys.maxsize
    fake.set_capacity(1)
    fake["beta"] = 2
    with raises(KVStoreFull):
        fake.commit()


def test_fake_kvstore_recording_off_by_default() -> None:
    """``record_calls=False`` (default) leaves ``calls`` empty."""
    fake = FakeKVStore()
    fake["alpha"] = 1
    fake.commit()
    del fake["alpha"]
    fake.reload()
    assert fake.calls == []


def test_fake_kvstore_records_delete_and_reload() -> None:
    """``record_calls=True`` captures ``__delitem__`` and ``reload``."""
    fake = FakeKVStore(record_calls=True)
    fake["alpha"] = 1
    fake.commit()
    del fake["alpha"]
    fake.reload()
    assert ("__delitem__", ("alpha",)) in fake.calls
    assert ("reload", ()) in fake.calls


def test_fake_kvstore_reset_corrupt_clears_simulation() -> None:
    """``reset_corrupt`` undoes a prior ``simulate_corrupt``."""
    fake = FakeKVStore()
    fake["alpha"] = 1
    fake.commit()
    fake.simulate_corrupt()
    fake.reset_corrupt()
    fake.reload()  # would raise if still simulated
    assert fake["alpha"] == 1


def test_fake_kvstore_initial_payload_seeds_state() -> None:
    """``initial_payload`` bypasses construction and seeds the backend."""
    seed_store = FakeKVStore()
    seed_store["seed"] = 42
    seed_store.commit()
    payload = seed_store.raw_payload
    fresh = FakeKVStore(initial_payload=payload)
    assert fresh["seed"] == 42


# ---------------------------------------------------------------------------
# Backend internals — defensive paths exercised directly
# ---------------------------------------------------------------------------


def test_memory_backend_save_enforces_capacity_directly() -> None:
    """The backend-level capacity check fires when called outside ``KVStore``.

    KVStore.commit pre-checks capacity, but the backend keeps a
    defensive guard so test fakes and any future code that calls
    ``backend.save`` directly still surface the right exception.
    """
    backend = MemoryBackend(capacity=4)
    with raises(KVStoreFull):
        backend.save(b"x" * 100)


def test_memory_backend_reset_corrupt_clears_flag() -> None:
    """``reset_corrupt`` is the inverse of ``force_corrupt``."""
    backend = MemoryBackend()
    backend.force_corrupt()
    backend.reset_corrupt()
    assert backend.load() == b""


def test_base_backend_load_save_raise_notimplementederror() -> None:
    """The abstract ``Backend`` base raises on both methods.

    Confirms subclasses can't accidentally inherit a no-op ``load`` or
    ``save`` and silently no-op writes.
    """
    from chumicro_kvstore.core import Backend
    backend = Backend()
    with raises(NotImplementedError):
        backend.load()
    with raises(NotImplementedError):
        backend.save(b"")
