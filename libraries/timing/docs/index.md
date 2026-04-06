# chumicro-timing

Cross-runtime millisecond tick helpers and periodic timing utilities for CircuitPython, MicroPython, and CPython.

All timing is non-blocking — nothing in this library calls `time.sleep()`.

## Quick example

```python
from chumicro_timing import Heartbeat, ticks_ms

heartbeat = Heartbeat(period_ms=1000)

while True:
    now = ticks_ms()
    if heartbeat.poll(now):
        print("one second elapsed")
    # ... do other work ...
```

## Documentation

- [User Guide](guide.md) — getting started, usage patterns, platform notes
- [API Reference](api.md) — full API documentation
- [Testing Helpers](testing.md) — using `FakeTicks` in your tests

---

[← All ChuMicro Libraries](https://chumicro.github.io/ChuMicro/)

[Source](https://github.com/ChuMicro/ChuMicro/tree/develop/libraries/timing) · [PyPI](https://pypi.org/project/chumicro-timing/) · [Bundle](https://github.com/ChuMicro/ChuMicro-Bundle)
