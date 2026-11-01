# User Guide

## Overview

`chumicro-compat` adds standard-library features that CircuitPython and MicroPython leave out, under the same names on all three runtimes.  It holds one: `functools.partial`, imported from `chumicro_compat.functools`.

`partial(func, first_argument)` returns a new function with `first_argument` already filled in.  Calling the new function calls `func` with the filled-in arguments first, followed by the arguments given at the call.

## Getting started

Make one function per LED, then fade both pretend LEDs up and down forever:

```python
import time

from chumicro_compat.functools import partial


def set_led(pin, brightness, label="LED"):
    print(f"{label} on pin {pin}: {brightness}%")


# set_status_led(50) now runs set_led(13, 50, label="status LED").
set_status_led = partial(set_led, 13, label="status LED")
set_power_led = partial(set_led, 2, label="power LED")
leds = [set_status_led, set_power_led]

brightness = 0
step = 25
while True:
    for set_brightness in leds:
        set_brightness(brightness)

    brightness += step
    if brightness == 0 or brightness == 100:
        step = -step

    time.sleep(0.5)
```

The first pass prints:

```
status LED on pin 13: 0%
power LED on pin 2: 0%
```

## Keyword arguments

`partial` fills in keyword arguments the same way.  A keyword given at the call replaces the filled-in one for that call only:

```python
from chumicro_compat.functools import partial


def connect(host, port=80, timeout=5):
    print(f"connecting to {host}:{port} (timeout={timeout}s)")


connect_api = partial(connect, "api.example.com", port=443)
connect_api()              # connecting to api.example.com:443 (timeout=5s)
connect_api(timeout=10)    # connecting to api.example.com:443 (timeout=10s)
```

## Callbacks that carry their own context

A button handler or a scheduler calls its callback with the event alone, such as a time or a value.  `partial` fills in the pin number ahead of time, so each callback knows its own pin without a global variable:

```python
from chumicro_compat.functools import partial


def on_button_press(pin_number, event_ms):
    print(f"button on pin {pin_number} pressed at {event_ms} ms")


handle_button_0 = partial(on_button_press, 0)
handle_button_4 = partial(on_button_press, 4)

handle_button_0(1000)   # button on pin 0 pressed at 1000 ms
handle_button_4(2500)   # button on pin 4 pressed at 2500 ms
```

## Looking inside a partial

A partial keeps the wrapped function in `func`, the filled-in positional arguments in `args`, and the filled-in keywords in `keywords`.  CPython's `functools.partial` has the same three attributes:

```python
from chumicro_compat.functools import partial


def connect(host, port, *, tls=False):
    return f"{host}:{port} tls={tls}"


broker = partial(connect, "broker.local", tls=True)
print(broker.func)       # <function connect ...>
print(broker.args)       # ('broker.local',)
print(broker.keywords)   # {'tls': True}
print(broker(1883))      # broker.local:1883 tls=True
```

A partial over a function written in Python works on every runtime.  A partial that passes a keyword to a built-in, such as `partial(int, base=16)`, works on CPython only.  MicroPython and CircuitPython built-ins take those arguments by position, so calling that partial raises `TypeError` there.

## Platform notes

| Runtime | What `chumicro_compat.functools.partial` is |
|---|---|
| CPython | The standard library's `functools.partial` |
| MicroPython | A small pure-Python version |
| CircuitPython | A small pure-Python version |

Calling a partial, its `func`, `args`, and `keywords` attributes, and its `repr()` behave the same on all three runtimes.

## Examples

| Example | What it shows |
|---|---|
| [`partial_basic.py`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/compat/examples/partial_basic.py) | Fills in a pin and a label with `partial`, replaces the label in one call, keeps the new functions in a list of callbacks, and fades two pretend LEDs forever.  Runs on CPython, MicroPython, and CircuitPython with no wiring. |

---

<div class="chumicro-footer" markdown>

[← Home](index.md)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/compat) · \
[PyPI](https://pypi.org/project/chumicro-compat/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
