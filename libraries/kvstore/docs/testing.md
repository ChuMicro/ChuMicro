# Testing Helpers

`chumicro_kvstore.testing` holds `FakeKVStore`, a stand-in for the board storage a `KVStore` saves to: CircuitPython's NVM, ESP32's NVS, or a flash file.  `FakeKVStore` is a real `KVStore` that keeps its saved bytes in memory, so every test runs the same code a board runs.  It adds hooks for a full store, damaged data, and a record of calls.  `pip install chumicro-kvstore pytest` installs everything the tests on this page import.  Project deploys and the board bundles leave the module out.

## The smallest test

Save this as `test_boot_count.py` and run `pytest test_boot_count.py`:

```python
from chumicro_kvstore.testing import FakeKVStore


def test_boot_count_survives_a_reboot():
    store = FakeKVStore()
    store["boot_count"] = 1
    store.commit()

    rebooted = FakeKVStore(initial_payload=store.raw_payload)
    assert rebooted["boot_count"] == 1
```

`raw_payload` holds the bytes the last save wrote.  A second `FakeKVStore` built from those bytes plays the board after a reboot.

## `FakeKVStore`

`FakeKVStore` answers every `KVStore` call: `store[key]`, `get`, `commit()`, `commit_if_changed()`, `reload()`, `bytes_used`, `is_corrupt`, and the rest.

| Argument or call | What it does |
|---|---|
| `FakeKVStore(capacity=None)` | Caps a save at `capacity` bytes.  A larger save raises `KVStoreFull`.  `None` means no cap. |
| `FakeKVStore(initial_payload=None)` | Starts from saved bytes, such as another store's `raw_payload`. |
| `FakeKVStore(record_calls=False)` | `True` records each call in `calls`. |
| `set_capacity(capacity)` | Changes the cap mid-test. |
| `raw_payload` | The bytes the last save wrote. |
| `simulate_corrupt()` | Damages the saved bytes.  The next `reload()` raises `KVStoreCorrupt`, and the values in memory stay as they were. |
| `reset_corrupt()` | Repairs the saved bytes again. |
| `calls` | With `record_calls=True`, one `(method, args)` tuple per call to `__setitem__`, `__delitem__`, `commit`, `commit_if_changed`, or `reload`. |

A small `capacity` raises `KVStoreFull` on the laptop, the way a board with little storage does.  The [guide](guide.md#how-much-fits) lists how much each board holds.

```python
from chumicro_kvstore import KVStoreFull
from chumicro_kvstore.testing import FakeKVStore


def test_dropping_a_key_makes_room():
    store = FakeKVStore(capacity=64)
    store["a"] = "x" * 32
    store["b"] = "y" * 32
    try:
        store.commit()
        raise AssertionError("expected KVStoreFull")
    except KVStoreFull:
        del store["b"]
        store.commit()

    assert store.bytes_used <= 64
```

`set_capacity()` shrinks the store under values that already fit:

```python
from chumicro_kvstore import KVStoreFull
from chumicro_kvstore.testing import FakeKVStore


def test_a_smaller_store_refuses_the_same_values():
    store = FakeKVStore(capacity=1024)
    store["a"] = "x" * 200
    store.commit()

    store.set_capacity(64)
    try:
        store.commit()
        raise AssertionError("expected KVStoreFull")
    except KVStoreFull:
        pass
```

`simulate_corrupt()` damages the saved data, so a test checks what a program does with it:

```python
from chumicro_kvstore import KVStoreCorrupt
from chumicro_kvstore.testing import FakeKVStore


def test_reload_reports_damaged_data():
    store = FakeKVStore()
    store["x"] = 1
    store.commit()
    store.simulate_corrupt()

    try:
        store.reload()
        raise AssertionError("expected KVStoreCorrupt")
    except KVStoreCorrupt:
        pass
    assert store["x"] == 1
```

Building a store from damaged bytes raises nothing.  The store starts empty with `is_corrupt` set, so the program keeps running:

```python
from chumicro_kvstore.testing import FakeKVStore


def test_a_new_store_recovers_from_garbage():
    store = FakeKVStore(initial_payload=b"\xff" * 32)

    assert store.is_corrupt is True
    assert len(store) == 0
```

`record_calls=True` shows how a program talks to its store.  The list starts with the `reload` a store makes when it is built:

```python
from chumicro_kvstore.testing import FakeKVStore


class BootCounter:
    def __init__(self, store):
        self.store = store

    def start(self):
        self.store["boots"] = self.store.get("boots", 0) + 1
        self.store.commit_if_changed()


def test_boot_counter_saves_once_per_boot():
    store = FakeKVStore(record_calls=True)
    BootCounter(store).start()

    assert store.calls == [
        ("reload", ()),
        ("__setitem__", ("boots", 1)),
        ("commit_if_changed", ()),
    ]
```

## API reference

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
