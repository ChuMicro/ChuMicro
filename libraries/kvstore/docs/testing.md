# Testing Helpers

`chumicro_kvstore.testing` provides `FakeKVStore` — an in-memory `KVStore` with explicit corruption + capacity hooks for downstream tests.  It wraps the real `MemoryBackend`, so every assertion you write against the public `KVStore` API exercises the same code path the production runtime takes.  Downstream consumers import this rather than inventing ad-hoc mocks.

## Usage

```python
from chumicro_kvstore.testing import FakeKVStore

def test_boot_counter_persists():
    store = FakeKVStore()
    store["boot_count"] = 1
    store.commit()

    # Re-construct against the same underlying payload to simulate reboot.
    fresh = FakeKVStore(initial_payload=store.raw_payload)
    assert fresh["boot_count"] == 1
```

## Simulating a small NVM

CP NVM on small boards is 256 bytes.  Use `capacity=` to drive `KVStoreFull` deterministically without needing the real hardware:

```python
from chumicro_kvstore import KVStoreFull
from chumicro_kvstore.testing import FakeKVStore

def test_dropping_keys_recovers_from_full():
    store = FakeKVStore(capacity=64)            # tight on purpose
    store["a"] = "x" * 32
    store["b"] = "y" * 32
    try:
        store.commit()
        raise AssertionError("expected KVStoreFull")
    except KVStoreFull:
        del store["b"]
        store.commit()                          # succeeds now

    assert store.bytes_used <= 64
```

`set_capacity(new_capacity)` adjusts the limit mid-test if you want to cross the threshold from below:

```python
store = FakeKVStore(capacity=1024)
store["a"] = "x" * 200
store.commit()                                   # fits

store.set_capacity(64)                           # tighten
try:
    store["a"] = "x" * 200
    store.commit()
except KVStoreFull:
    pass                                         # expected
```

## Simulating corruption

`simulate_corrupt()` marks the underlying memory backend corrupt; the next `reload()` (or `KVStore` re-construction) surfaces a corruption event.  In-memory state stays intact until explicitly reloaded — matching the real device behavior, where in-flight state isn't poisoned by a backend-level fault.

```python
from chumicro_kvstore import KVStoreCorrupt
from chumicro_kvstore.testing import FakeKVStore

def test_reload_raises_on_corrupt():
    store = FakeKVStore()
    store["x"] = 1
    store.commit()
    store.simulate_corrupt()

    try:
        store.reload()
        raise AssertionError("expected KVStoreCorrupt")
    except KVStoreCorrupt:
        pass
```

The construction path treats corruption as recoverable — `is_corrupt` becomes `True` and the store resets to empty:

```python
def test_construction_recovers_from_corrupt():
    payload = b"\xff" * 32                       # garbage
    store = FakeKVStore(initial_payload=payload)
    assert store.is_corrupt is True
    assert len(store) == 0                       # blank, but usable
```

## Recording calls

Pass `record_calls=True` to capture every public-API call as a `(method, args)` tuple in `store.calls`:

```python
def test_publisher_only_commits_once_per_minute():
    store = FakeKVStore(record_calls=True)
    publisher = TelemetryPublisher(store=store, ...)

    for _ in range(60):
        publisher.tick()

    commit_calls = [event for event in store.calls if event[0] == "commit"]
    assert len(commit_calls) == 1
```

Recorded methods: `__setitem__`, `__delitem__`, `commit`, `commit_if_changed`, `reload`.

## Inspecting the raw payload

`raw_payload` returns the encoded msgpack bytes the backend currently holds.  Useful for round-trip assertions or for seeding a second `FakeKVStore` from the first's persisted state:

```python
seeded = FakeKVStore()
seeded["boot_count"] = 7
seeded.commit()

restarted = FakeKVStore(initial_payload=seeded.raw_payload)
assert restarted["boot_count"] == 7
```

## Usage from other libraries

Libraries that depend on `chumicro-kvstore` can import the fake directly:

```python
from chumicro_kvstore.testing import FakeKVStore
```

Project convention: libraries that expose injectable services ship their own test fakes alongside the production code.

## API Reference

::: chumicro_kvstore.testing
    options:
      members:
        - FakeKVStore

---

<div class="chumicro-footer" markdown>

[← Home](index.md)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/kvstore) · \
[PyPI](https://pypi.org/project/chumicro-kvstore/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
