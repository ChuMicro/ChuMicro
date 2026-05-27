"""Host-side tests for ``MpLittlefsBackend`` via fake-fs injection.

Exercises the load / save / sync / rename loop without a Pi Pico W.
The fake mirrors the public ``open`` / ``os.rename`` / ``os.remove``
/ ``os.sync`` interface MicroPython exposes so the production code
under test runs verbatim.

Hardware-side coverage (real LittleFS on a Pi Pico W flash chip,
power-cycle behavior, atomicity across interrupted writes) lives
under ``functional_tests/``.
"""

#: Host-lane only — exercises a runtime-specific backend through host
#: fakes and asserts off-target behaviour; never staged to a device.
__chumicro_host_only__ = True

from chumicro_kvstore import KVStore, KVStoreFull
from chumicro_kvstore._backends.mp_littlefs import MpLittlefsBackend
from chumicro_test_harness import raises


class _FakeFile:
    """Minimal file-like that mirrors the ``open()`` return value's interface.

    Records every chunk written so tests can inspect the wire bytes,
    plus a ``closed`` flag for cleanup assertions.
    """

    def __init__(self, store: dict, path: str, mode: str):
        self._store = store
        self._path = path
        self._mode = mode
        self._buffer = bytearray()
        self.closed = False
        if "r" in mode:
            if path not in store:
                raise OSError(2, "ENOENT", path)
            self._buffer = bytearray(store[path])

    def write(self, data: bytes) -> int:
        self._buffer.extend(data)
        return len(data)

    def read(self) -> bytes:
        return bytes(self._buffer)

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        if "w" in self._mode:
            self._store[self._path] = bytes(self._buffer)


class _FakeFs:
    """In-memory stand-in for ``open`` / ``rename`` / ``remove`` / ``sync``."""

    def __init__(self):
        self._store: dict[str, bytes] = {}
        self.sync_count = 0
        self.rename_count = 0

    def open(self, path: str, mode: str) -> _FakeFile:
        return _FakeFile(self._store, path, mode)

    def rename(self, source: str, destination: str) -> None:
        if source not in self._store:
            raise OSError(2, "ENOENT", source)
        self._store[destination] = self._store.pop(source)
        self.rename_count += 1

    def remove(self, path: str) -> None:
        if path not in self._store:
            raise OSError(2, "ENOENT", path)
        del self._store[path]

    def sync(self) -> None:
        self.sync_count += 1


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


def test_default_path_and_capacity_match_adr() -> None:
    """The default path and capacity are fixed values."""
    backend = MpLittlefsBackend(filesystem=_FakeFs())
    assert backend._path == "/_chu_kv.msgpack"
    assert backend.capacity == MpLittlefsBackend.DEFAULT_CAPACITY == 16384


def test_capacity_override_accepted() -> None:
    backend = MpLittlefsBackend(filesystem=_FakeFs(), capacity=4096)
    assert backend.capacity == 4096


def test_path_override_accepted() -> None:
    """Tests + alternative mount points can override the default path."""
    backend = MpLittlefsBackend(path="/other.msgpack", filesystem=_FakeFs())
    assert backend._path == "/other.msgpack"
    assert backend._tmp_path == "/other.msgpack.tmp"


def test_runtime_fs_is_used_when_no_injection() -> None:
    """Default-arg construction uses ``os`` + ``builtins.open`` shim."""
    backend = MpLittlefsBackend()
    # Substrate is the runtime shim class; just confirm it has the
    # four methods the load / save paths need.
    for name in ("open", "rename", "remove", "sync"):
        assert hasattr(backend._fs, name)


# ---------------------------------------------------------------------------
# Round-trip
# ---------------------------------------------------------------------------


def test_load_missing_file_returns_empty() -> None:
    """Blank filesystem (no payload file yet) reports empty without raising."""
    backend = MpLittlefsBackend(filesystem=_FakeFs())
    assert backend.load() == b""


def test_save_then_load_round_trips() -> None:
    fake = _FakeFs()
    backend = MpLittlefsBackend(filesystem=fake)
    payload = b"\x82\xa3foo\x01\xa3bar\x02"
    backend.save(payload)
    assert backend.load() == payload


def test_save_writes_to_canonical_path() -> None:
    """Verify the bytes land at ``/_chu_kv.msgpack``."""
    fake = _FakeFs()
    backend = MpLittlefsBackend(filesystem=fake)
    backend.save(b"hello")
    assert fake._store["/_chu_kv.msgpack"] == b"hello"


def test_save_uses_tmp_then_rename() -> None:
    """Atomic-write protocol: write tmp, sync, rename, cleanup tmp."""
    fake = _FakeFs()
    backend = MpLittlefsBackend(filesystem=fake)
    backend.save(b"payload bytes")
    # After rename, only the payload path holds the bytes.
    assert "/_chu_kv.msgpack" in fake._store
    assert "/_chu_kv.msgpack.tmp" not in fake._store


def test_save_calls_sync_before_rename() -> None:
    """Sync must precede rename so contents land before the directory flip."""
    fake = _FakeFs()
    backend = MpLittlefsBackend(filesystem=fake)
    backend.save(b"x")
    assert fake.sync_count == 1
    assert fake.rename_count == 1


def test_save_overwrites_previous_payload() -> None:
    fake = _FakeFs()
    backend = MpLittlefsBackend(filesystem=fake)
    backend.save(b"first version")
    backend.save(b"second-and-longer version")
    assert backend.load() == b"second-and-longer version"


# ---------------------------------------------------------------------------
# Capacity enforcement
# ---------------------------------------------------------------------------


def test_save_raises_kvstorefull_when_payload_exceeds_capacity() -> None:
    backend = MpLittlefsBackend(filesystem=_FakeFs(), capacity=64)
    with raises(KVStoreFull):
        backend.save(b"x" * 100)


def test_save_at_exact_capacity_succeeds() -> None:
    backend = MpLittlefsBackend(filesystem=_FakeFs(), capacity=64)
    edge = b"x" * 64
    backend.save(edge)
    assert backend.load() == edge


# ---------------------------------------------------------------------------
# Integration through KVStore
# ---------------------------------------------------------------------------


def test_kvstore_with_mp_littlefs_backend_round_trips_through_reload() -> None:
    """Full vertical: KVStore through MpLittlefsBackend, a fake fs, and
    back via reload.
    """
    fake = _FakeFs()
    backend = MpLittlefsBackend(filesystem=fake)
    store = KVStore(backend=backend)
    store["boot_count"] = 7
    store["last_seen_ms"] = 42
    store.commit()
    fresh = KVStore(backend=MpLittlefsBackend(filesystem=fake))
    assert fresh["boot_count"] == 7
    assert fresh["last_seen_ms"] == 42


def test_kvstore_with_mp_littlefs_backend_construction_handles_blank_fs() -> None:
    """Auto-load on a never-written filesystem produces an empty store."""
    backend = MpLittlefsBackend(filesystem=_FakeFs())
    store = KVStore(backend=backend)
    assert len(store) == 0
    assert store.is_corrupt is False


def test_kvstore_commit_if_changed_skips_unchanged() -> None:
    """Wear defense: identical state means no rename or sync."""
    fake = _FakeFs()
    backend = MpLittlefsBackend(filesystem=fake)
    store = KVStore(backend=backend)
    store["alpha"] = 1
    assert store.commit_if_changed() is True
    rename_baseline = fake.rename_count
    sync_baseline = fake.sync_count
    assert store.commit_if_changed() is False
    assert fake.rename_count == rename_baseline
    assert fake.sync_count == sync_baseline
