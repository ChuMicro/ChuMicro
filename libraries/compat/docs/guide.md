# User Guide

## Overview

`chumicro-compat` holds two kinds of shim.  `chumicro_compat.functools` reimplements a CPython standard-library feature that MicroPython and CircuitPython leave out, so library code uses the familiar pattern on all three runtimes.  `chumicro_compat.wiring` resolves pins and buses from MCU GPIO numbers, so one construction block runs on both device runtimes.

On CPython the real C implementation of `partial` is re-exported for zero overhead.  The wiring resolvers raise there, because a laptop has no GPIO, and a test injects a fake in their place.

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

def connect(host, port, *, tls=False):
    return f"{host}:{port} tls={tls}"

p = partial(connect, "broker.local", tls=True)
print(p.func)       # <function connect ...>
print(p.args)        # ('broker.local',)
print(p.keywords)    # {'tls': True}
print(p(1883))       # broker.local:1883 tls=True
```

> The example uses a pure-Python function so it runs identically on
> every runtime.  Passing a keyword to a C builtin like `int(x, base=16)`
> works on CPython but raises `TypeError` on MicroPython / CircuitPython,
> whose builtins take those arguments positionally only.

## Pins and buses by GPIO number

The wire between a board and a part has one identity, its MCU GPIO number, and each runtime spells it differently: `machine.Pin(6)` on MicroPython, `board.GP6` or `board.IO6` on CircuitPython, with the alias changing per board definition.  `chumicro_compat.wiring` takes the number and returns what the runtime's own API takes, so moving an app between runtimes leaves its pin references alone.

### An output pin

`digital_output(gpio, value=)` returns a callable pin: `pin(1)` drives high, `pin(0)` drives low, and `pin()` reads the level back.  On MicroPython that is a `machine.Pin` in output mode; on CircuitPython it is a `digitalio.DigitalInOut` behind the same call shape.  `value` is the level driven at construction, so a chip select idles high from its first instant.

```python
from chumicro_compat.wiring import digital_output

chip_select = digital_output(5, value=1)
data_command = digital_output(8, value=0)
chip_select(0)   # assert
chip_select(1)   # release
```

### SPI and I2C buses

`spi_bus` and `i2c_bus` return the runtime's native bus on the GPIO numbers given: `machine.SPI` or `busio.SPI`, `machine.I2C` or `busio.I2C`.  The first argument is the MicroPython controller id, which decides which pins are legal on rp2 and esp32; CircuitPython derives the controller from the pins and ignores it.

```python
from chumicro_compat.wiring import i2c_bus, spi_bus

spi = spi_bus(0, sck=6, mosi=7, baudrate=40_000_000)
i2c = i2c_bus(0, scl=5, sda=4, frequency=100_000)
```

On CircuitPython `spi_bus` locks the bus once to apply `baudrate`, `polarity`, and `phase`, so a driver that only writes needs no further configuration.  A consumer that reconfigures the bus per transaction, `fourwire.FourWire` for one, still takes its own baudrate.  `i2c_bus` defaults `frequency` to 400 kHz on both runtimes, where MicroPython's own default is 400 kHz and CircuitPython's is 100 kHz.  A part rated for 100 kHz, such as a PCF8574 LCD backpack, wants the number passed.

### Pin objects pass through

A port whose pins are not a flat integer, stm32's `PA5` for one, hands the runtime's pin object in place of the number.  A `machine.Pin` comes back as it was given, mode and all, and a `microcontroller.Pin` is wrapped the same way a number is.  A bus resolver given an already-constructed bus returns it unchanged.

### One file on both runtimes

[`blink.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/compat/examples/blink.py) is one example file marked for both device runtimes: it resolves GPIO15 with `digital_output` and toggles it on a `chumicro_timing` deadline.  That number is a LOLIN S2 Mini's onboard LED and a Pi Pico W's GP15 header pin.

## Platform notes

| Runtime | `functools.partial` | `wiring` |
|---|---|---|
| CPython | Re-exports the C implementation, zero overhead | Raises `RuntimeError`; inject a fake |
| MicroPython | Pure-Python polyfill | `machine.Pin`, `machine.SPI`, `machine.I2C` |
| CircuitPython | Pure-Python polyfill | `digitalio.DigitalInOut` behind a callable, `busio.SPI`, `busio.I2C` |

The public API is identical across all runtimes.  Code that imports `partial` from `chumicro_compat.functools` works on any supported runtime without changes, and code that resolves its pins through `chumicro_compat.wiring` carries the same GPIO numbers to both device runtimes.

## Examples

The [examples](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/compat/examples) directory contains complete runnable scripts:

| Example | What it shows |
|---|---|
| `partial_basic.py` | Freeze one positional argument to a function |
| `partial_keyword_override.py` | Freeze keyword args, override at call time |
| `partial_callback.py` | Wire a callback with frozen context (embedded pattern) |
| `blink.py` | Blink GPIO15 from one file that runs on both device runtimes |

---

<div class="chumicro-footer" markdown>

[← Home](index.md)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/compat) · \
[PyPI](https://pypi.org/project/chumicro-compat/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
