"""Host-side tests for ``MpNvsBackend`` via fake-NVS injection.

Exercises the load / save / commit loop without an ESP32.  The fake
mirrors the public ``esp32.NVS`` interface MicroPython exposes:
``set_blob(key, value)``, ``get_blob(key, buffer) -> length``,
``erase_key(key)``, ``commit()``.

Hardware-side coverage (real ``esp32.NVS`` namespace, power-cycle
behavior) lives under ``functional_tests/``.
"""

#: Host-lane only — exercises a runtime-specific backend through host
#: fakes and asserts off-target behaviour; never staged to a device.
__chumicro_host_only__ = True

from chumicro_kvstore import KVStore, KVStoreFull
from chumicro_kvstore._backends.mp_nvs import MpNvsBackend
from chumicro_test_harness import raises


class _FakeNvs:
    """Minimal stand-in for ``esp32.NVS`` for host tests.

    Mirrors the wire-level interface the real MP wrapper exposes:
    set_blob writes a ``bytes`` value under a key; get_blob copies
    into a caller-allocated buffer and returns the length; missing
    keys raise ``OSError``; ``commit`` is a no-op (the fake is
    already-committed).
    """

    def __init__(self):
        self._values: dict[str, bytes] = {}
        self.commit_count = 0

    def set_blob(self, key: str, value: bytes) -> None:
        self._values[key] = bytes(value)

    def get_blob(self, key: str, buffer: bytearray) -> int:
        if key not in self._values:
            raise OSError(2, "ENOENT")
        value = self._values[key]
        buffer[: len(value)] = value
        return len(value)

    def erase_key(self, key: str) -> None:
        del self._values[key]

    def commit(self) -> None:
        self.commit_count += 1


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


def test_default_capacity_matches_class_constant() -> None:
    """Default capacity is sized for small-key state; users override for larger."""
    backend = MpNvsBackend(nvs=_FakeNvs())
    assert backend.capacity == MpNvsBackend.DEFAULT_CAPACITY == 512


def test_capacity_override_accepted() -> None:
    backend = MpNvsBackend(nvs=_FakeNvs(), capacity=4096)
    assert backend.capacity == 4096


def test_runtime_acquisition_raises_on_cpython() -> None:
    """Default-arg construction raises ``RuntimeError`` outside MP-ESP32."""
    with raises(RuntimeError):
        MpNvsBackend()  # would try `import esp32`


def test_namespace_and_payload_key_constants_match_adr() -> None:
    """The NVS namespace and key are fixed values."""
    assert MpNvsBackend.NAMESPACE == "chu_kv"
    assert MpNvsBackend.PAYLOAD_KEY == "payload"


# ---------------------------------------------------------------------------
# Round-trip
# ---------------------------------------------------------------------------


def test_load_missing_key_returns_empty() -> None:
    """Blank NVS (no payload key yet) reports empty without raising."""
    backend = MpNvsBackend(nvs=_FakeNvs())
    assert backend.load() == b""


def test_save_then_load_round_trips() -> None:
    fake = _FakeNvs()
    backend = MpNvsBackend(nvs=fake)
    payload = b"\x82\xa3foo\x01\xa3bar\x02"  # msgpack {"foo": 1, "bar": 2}
    backend.save(payload)
    assert backend.load() == payload


def test_save_writes_to_canonical_namespace_and_key() -> None:
    """The payload lands at namespace=chu_kv, key=payload."""
    fake = _FakeNvs()
    backend = MpNvsBackend(nvs=fake)
    backend.save(b"hello")
    # Fake records under its own dict; the key the backend uses is
    # what real NVS would see.
    assert fake._values[MpNvsBackend.PAYLOAD_KEY] == b"hello"


def test_save_commits_after_each_write() -> None:
    """Every save calls ``commit`` so the bytes survive a power cycle."""
    fake = _FakeNvs()
    backend = MpNvsBackend(nvs=fake)
    backend.save(b"first")
    assert fake.commit_count == 1
    backend.save(b"second")
    assert fake.commit_count == 2


def test_save_overwrites_previous_payload() -> None:
    fake = _FakeNvs()
    backend = MpNvsBackend(nvs=fake)
    backend.save(b"first version")
    backend.save(b"second-and-longer version")
    assert backend.load() == b"second-and-longer version"


# ---------------------------------------------------------------------------
# Capacity enforcement
# ---------------------------------------------------------------------------


def test_save_raises_kvstorefull_when_payload_exceeds_capacity() -> None:
    backend = MpNvsBackend(nvs=_FakeNvs(), capacity=64)
    with raises(KVStoreFull):
        backend.save(b"x" * 100)


def test_save_at_exact_capacity_succeeds() -> None:
    backend = MpNvsBackend(nvs=_FakeNvs(), capacity=64)
    edge = b"x" * 64
    backend.save(edge)
    assert backend.load() == edge


# ---------------------------------------------------------------------------
# Integration through KVStore
# ---------------------------------------------------------------------------


def test_kvstore_with_mp_nvs_backend_round_trips_through_reload() -> None:
    """Full vertical: KVStore through MpNvsBackend, a fake NVS, and
    back via reload.
    """
    fake = _FakeNvs()
    backend = MpNvsBackend(nvs=fake)
    store = KVStore(backend=backend)
    store["boot_count"] = 7
    store["last_seen_ms"] = 42
    store.commit()
    # Fresh KVStore against the same fake (equivalent to a reboot
    # since NVS persists across power cycles in production).
    fresh = KVStore(backend=MpNvsBackend(nvs=fake))
    assert fresh["boot_count"] == 7
    assert fresh["last_seen_ms"] == 42


def test_kvstore_with_mp_nvs_backend_construction_handles_blank_nvs() -> None:
    """Auto-load on a never-written namespace produces an empty store."""
    backend = MpNvsBackend(nvs=_FakeNvs())
    store = KVStore(backend=backend)
    assert len(store) == 0
    assert store.is_corrupt is False


def test_kvstore_commit_if_changed_skips_unchanged() -> None:
    """Wear defense: identical state means no NVS commit."""
    fake = _FakeNvs()
    backend = MpNvsBackend(nvs=fake)
    store = KVStore(backend=backend)
    store["alpha"] = 1
    assert store.commit_if_changed() is True
    commit_baseline = fake.commit_count
    assert store.commit_if_changed() is False
    assert fake.commit_count == commit_baseline
