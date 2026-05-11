# User Guide

## Overview

`chumicro-compat` provides lightweight reimplementations of CPython standard-library features that are missing or incomplete on MicroPython and CircuitPython.  It allows library authors to use familiar Python patterns across all three runtimes without depending on modules that don't exist on microcontrollers.

On CPython, the real C implementations are re-exported for zero overhead.  On MicroPython and CircuitPython, pure-Python polyfills provide the same API.

## functools.partial

`functools.partial` freezes some arguments to a callable, producing a new callable with fewer parameters.  CPython includes it in the standard library, but MicroPython and CircuitPython do not.

### Basic usage

```python
from chumicro_compat.functools import partial

def set_led(pin: int, brightness: int) -> None:
    """Set an LED pin to a brightness level.

    Args:
        pin: GPIO pin number.
        brightness: Brightness percentage (0–100).
    """
    print(f"pin {pin} → {brightness}%")

# Freeze the pin number.  Now set_status_led only needs brightness.
set_status_led = partial(set_led, 13)
set_status_led(50)   # pin 13 → 50%
set_status_led(100)  # pin 13 → 100%
```

### Freezing keyword arguments

Keyword arguments can be frozen and overridden at call time:

```python
from chumicro_compat.functools import partial

def connect(host: str, port: int = 80, timeout: int = 5) -> None:
    """Simulate a connection.

    Args:
        host: Server hostname.
        port: TCP port number.
        timeout: Connection timeout in seconds.
    """
    print(f"connecting to {host}:{port} (timeout={timeout}s)")

# Freeze host and port; timeout can still be overridden.
connect_api = partial(connect, "api.example.com", port=443)
connect_api()              # timeout=5 (default)
connect_api(timeout=10)    # timeout=10 (overridden)
```

### Wiring callbacks with frozen context

A common embedded pattern is binding a hardware pin or device reference into a callback so the handler doesn't need global state:

```python
from chumicro_compat.functools import partial

def on_button_press(pin_number: int, event_ms: int) -> None:
    """Handle a button press event.

    Args:
        pin_number: GPIO pin the button is connected to.
        event_ms: Timestamp of the press in milliseconds.
    """
    print(f"button on pin {pin_number} pressed at {event_ms} ms")

# Wire pin 0 into the callback.  The runner passes event_ms at call time.
handler = partial(on_button_press, 0)
handler(12345)  # button on pin 0 pressed at 12345 ms
```

### Inspecting a partial object

The public attributes match CPython's `functools.partial`:

```python
from chumicro_compat.functools import partial

p = partial(int, "ff", base=16)
print(p.func)       # <class 'int'>
print(p.args)        # ('ff',)
print(p.keywords)    # {'base': 16}
print(p())           # 255
```

## Platform notes

| Runtime | Implementation |
|---|---|
| CPython | Re-exports `functools.partial` (C implementation, zero overhead) |
| MicroPython | Pure-Python polyfill |
| CircuitPython | Pure-Python polyfill |

The public API is identical across all runtimes.  Code that imports `partial` from `chumicro_compat.functools` will work on any supported runtime without changes.

## Examples

The [examples](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/compat/examples) directory contains complete runnable scripts:

| Example | What it shows |
|---|---|
| `partial_basic.py` | Freeze one positional argument to a function |
| `partial_keyword_override.py` | Freeze keyword args, override at call time |
| `partial_callback.py` | Wire a callback with frozen context (embedded pattern) |

---

<div class="chumicro-footer" markdown>

[← Home](index.md)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/compat) · \
[PyPI](https://pypi.org/project/chumicro-compat/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
