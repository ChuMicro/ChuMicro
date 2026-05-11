# chumicro-kvstore

**Tiny mutable key-value store for runtime state that survives reboot.**

Counters, timestamps, tokens, retry budgets — across CircuitPython, MicroPython, and CPython.  Backends auto-select per runtime (CP NVM with CRC framing, MP NVS, MP LittleFS, in-memory).  Not a config system: config is read-only at deploy time and lives in `chumicro-config`; KVStore is read-write at runtime.

## Quick example

```python
from chumicro_kvstore import KVStore
from chumicro_timing import ticks_ms

store = KVStore(backend="auto")              # picks the right backend per runtime
store["boot_count"] = store.get("boot_count", 0) + 1
store["last_seen_ms"] = ticks_ms()
store.commit()                                # one flush per logical change
```

## Documentation

- [User Guide](guide.md) — backends, auto-selection, commit semantics, sizing
- [API Reference](api.md) — full API documentation
- [Testing Helpers](testing.md) — `FakeKVStore` for downstream test suites

---

<div class="chumicro-footer" markdown>

[← All ChuMicro Libraries](../../)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/kvstore) · \
[PyPI](https://pypi.org/project/chumicro-kvstore/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
