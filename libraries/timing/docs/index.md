# chumicro-timing

**Cross-runtime millisecond tick helpers and periodic timing for CircuitPython, MicroPython, and CPython.**

Capture `ticks_ms()` once per pass through your loop and hand it to a `Rate` (a drift-free periodic cadence) or a `Deadline` (a single armed timeout).  Both are built on wrap-safe tick arithmetic, so the counter rollover on a board that has been up for weeks changes nothing.  All timing is non-blocking: nothing on the device path calls `time.sleep()` (the host-test `sleep_ms` shim in `chumicro_timing.testing` is the one exception, and it never deploys).

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

## Documentation

- [User Guide](guide.md): periodic cadence with `Rate`, sharing one timestamp across a loop, deadlines, choosing a wait, using the tick helpers directly, wraparound details, pairing with `chumicro-runner`
- [API Reference](api.md): the wrap-safe `ticks_ms` / `ticks_diff` / `ticks_add` helpers, the `Deadline` and `Rate` value objects, and the `Signal` / `wait_for` wait vocabulary
- [Testing Helpers](testing.md): using `FakeTicks` in your tests

---

<div class="chumicro-footer" markdown>

[← All ChuMicro Libraries](../../)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/timing) · \
[PyPI](https://pypi.org/project/chumicro-timing/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
