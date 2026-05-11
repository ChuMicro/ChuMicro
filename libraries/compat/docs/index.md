# chumicro-compat

**Cross-runtime compatibility polyfills for CircuitPython, MicroPython, and CPython.**

Lightweight reimplementations of CPython standard-library features missing on microcontroller runtimes — on CPython, the real C implementations are re-exported with no overhead.

## Quick example

```python
from chumicro_compat.functools import partial

def set_led(pin: int, brightness: int) -> None:
    """Set an LED pin to a brightness level."""
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

<div class="chumicro-footer" markdown>

[← All ChuMicro Libraries](../../)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/compat) · \
[PyPI](https://pypi.org/project/chumicro-compat/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
