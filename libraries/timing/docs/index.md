# chumicro-timing

**Cross-runtime millisecond tick helpers and periodic timing for CircuitPython, MicroPython, and CPython.**

All timing is non-blocking — nothing in this library calls `time.sleep()`.

## Quick example

```python
from chumicro_timing import Rate, ticks_ms

rate = Rate(1000, ticks_ms())

while True:
    now = ticks_ms()
    if rate.due(now):
        print("one second elapsed")
    # ... do other work ...
```

The value objects — `Deadline` (a single armed timeout) and `Rate` (drift-free periodic cadence) — build on the wrap-safe tick helpers.

## Documentation

- [User Guide](guide.md) — getting started, usage patterns, platform notes
- [API Reference](api.md) — full API documentation
- [Testing Helpers](testing.md) — using `FakeTicks` in your tests

---

<div class="chumicro-footer" markdown>

[← All ChuMicro Libraries](../../)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/timing) · \
[PyPI](https://pypi.org/project/chumicro-timing/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
