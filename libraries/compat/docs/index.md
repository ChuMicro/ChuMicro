# chumicro-compat

Cross-runtime compatibility polyfills for CircuitPython, MicroPython, and CPython.

Provides lightweight reimplementations of CPython standard-library features that are missing or incomplete on microcontroller runtimes.  On CPython, re-exports the real C implementations for zero overhead.

## Quick example

```python
from chumicro_compat.functools import partial


def set_led(pin, brightness):
    print(f"pin {pin} → {brightness}%")


# Freeze the pin, vary the brightness later.
set_status_led = partial(set_led, 13)
set_status_led(50)   # pin 13 → 50%
set_status_led(100)  # pin 13 → 100%
```

## Documentation

- [User Guide](guide.md) — what's polyfilled and why, usage patterns
- [API Reference](api.md) — full API documentation

---

[← All ChuMicro Libraries](https://chumicro.github.io/ChuMicro/) · [Source](https://github.com/ChuMicro/ChuMicro/tree/develop/libraries/compat) · [PyPI](https://pypi.org/project/chumicro-compat/) · [Bundle](https://github.com/ChuMicro/ChuMicro-Bundle)
