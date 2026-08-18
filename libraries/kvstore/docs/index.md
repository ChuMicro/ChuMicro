---
title: "chumicro-kvstore: storage that survives a reboot on CircuitPython and MicroPython"
---

# chumicro-kvstore

**Tiny mutable key-value store for runtime state that survives reboot.**

Counters, timestamps, tokens, and retry budgets that your program writes while it runs and still finds after a power cycle, on CircuitPython, MicroPython, and CPython.  You get a dict you assign to and `commit()` when the change matters; the backend is chosen for the runtime you are on (NVM with CRC framing on CircuitPython, NVS on ESP32 MicroPython, LittleFS elsewhere, in-memory on a host).

## Install

```bash
# CircuitPython (after `circup bundle-add ChuMicro/ChuMicro-Bundle`)
circup install chumicro_kvstore

# MicroPython
mpremote mip install github:ChuMicro/ChuMicro-Bundle/chumicro_kvstore

# CPython
pip install chumicro-kvstore
```

No board running yet?  [Start here](https://chumicro.com/ChuMicro/guides/start-here/) goes from a new board to your own code running on it.  [Installing libraries](https://chumicro.com/ChuMicro/guides/install/) covers registering the bundle, the experimental channel, and the pre-compiled `.mpy` packages.

## Quick example

```python
from chumicro_kvstore import KVStore
from chumicro_timing import ticks_ms  # separate install: chumicro-timing

store = KVStore(backend="auto")              # picks the right backend per runtime
store["boot_count"] = store.get("boot_count", 0) + 1
store["last_seen_ms"] = ticks_ms()
store.commit()                                # one flush per logical change
```

## Documentation

- [User Guide](guide.md): backends and `auto` selection, commit semantics, sizing and full-store handling, corruption handling, platform notes
- [API Reference](api.md): `KVStore` methods, `commit_if_changed`, and the `KVStoreFull` / `KVStoreCorrupt` exceptions
- [Testing Helpers](testing.md): using `FakeKVStore` in your tests

---

<div class="chumicro-footer" markdown>

[← All ChuMicro Libraries](../../)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/kvstore) · \
[PyPI](https://pypi.org/project/chumicro-kvstore/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
