# chumicro-kvstore

Tiny mutable key-value store for persisted runtime state — counters, timestamps, tokens, retry budgets — across CircuitPython, MicroPython, and CPython.

Backends auto-select per runtime (CP NVM with CRC framing, MP `esp32.NVS`, MP LittleFS, in-memory).  **Not** a config system — see [Decision 0030](https://github.com/ChuMicro/ChuMicro/blob/main/plans/decisions/0030-config-and-state.md) and [Decision 0034](https://github.com/ChuMicro/ChuMicro/blob/main/plans/decisions/0034-kvstore-api-and-backends.md) for the split rationale.

## Quick example

```python
from chumicro_kvstore import KVStore

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
