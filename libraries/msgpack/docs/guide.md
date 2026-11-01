# User Guide

## Overview

`chumicro-msgpack` turns Python values into compact bytes and back, in the [MessagePack](https://msgpack.org) format.  It does the job of `json.dumps` and `json.loads` in fewer bytes.  The saving counts when the bytes go into a few kilobytes of NVM or over a slow radio link.

`packb` and `unpackb` turn a value into bytes in memory and back.  `pack` and `unpack` write a value to a stream, such as a file or a socket, and read it back.  [Supported types](#supported-types) lists the values all four accept.

## Getting started

Pack a changing sensor reading once a second, print the bytes, and unpack them again:

```python
import time

from chumicro_msgpack import packb, unpackb

count = 0

while True:
    count += 1
    reading = {"count": count, "temp_c": 20.0 + (count % 10) / 2}

    data = packb(reading)                    # dict -> 20 bytes
    print(f"{len(data)} bytes: {data.hex()}")
    print(f"unpacked: {unpackb(data)}")      # bytes -> the same dict

    time.sleep(1)
```

The first pass prints:

```
20 bytes: 82a5636f756e7401a674656d705f63ca41a40000
unpacked: {'count': 1, 'temp_c': 20.5}
```

`json.dumps` turns the same reading into 28 bytes of text.

## When to use msgpack or `struct`

Python's `struct` module also packs values into compact bytes.  It packs a fixed layout, and msgpack packs values that describe themselves:

| | `struct` | msgpack |
|---|---|---|
| **Layout** | A format string such as `">HBf"`, which both sides must share | A type tag in front of every value |
| **Changing the fields** | Every reader needs the new format string | A reader skips the dict keys it does not know |
| **Size** | The smallest for a fixed layout | A byte or so per value for the tags, still far smaller than JSON |
| **Suits** | Sensor packets, register maps, and wire protocols with a spec | Settings dicts, saved state, and messages between devices that may run different firmware |

Pick `struct` when the layout never changes and both ends ship together.  Pick msgpack when the data is a dict, when its fields change between versions, or when a reader has to make sense of bytes without a format string.

## Bytes: `packb` and `unpackb`

`packb` returns the packed data as `bytes`.  `unpackb` turns it back into the value.  Use them to keep the bytes in hand: to save them in NVM, to measure their length before writing a header in front, or to pass them to a function that takes `bytes`.

```python
from chumicro_msgpack import packb, unpackb

packed = packb([1, "hello", None, True])
print(unpackb(packed))  # [1, 'hello', None, True]
```

`unpackb` accepts `bytes`, `bytearray`, and `memoryview`, so it unpacks straight from an existing buffer with no copy first.  `packb` builds the result in a growing `bytearray` and copies it to `bytes` at the end.  The copy takes as many bytes again as the packed result.

## Streams: `pack` and `unpack`

`pack(value, stream)` packs a value and writes it to any object with a `write()` method.  `unpack(stream)` reads one back from any object with a `read()` method.  Both match the functions of the same name in CircuitPython's built-in `msgpack` module.

```python
from io import BytesIO

from chumicro_msgpack import pack, unpack

stream = BytesIO()
pack({"key": [1, 2, 3]}, stream)

stream.seek(0)
print(unpack(stream))  # {'key': [1, 2, 3]}
```

Write one value per stream.  On MicroPython and CPython, `unpack` reads everything left in the stream and raises `ValueError` when bytes remain after the first value.  On a CircuitPython board with the built-in module, `pack` writes each piece as it encodes it.  On every other runtime, `pack` calls `packb` and writes the result, so it needs the same memory as `packb`.

## Number keys for smaller data

A short string key costs one byte per character plus one, so `"humidity"` takes nine bytes every time it is packed.  A small integer key from 0 to 127 takes one byte.  Where space is tight, as in NVM, give each field a number and name the numbers with constants to keep the code readable:

```python
import json

from chumicro_msgpack import packb

COUNT = 0
TEMP_C = 1
HUMIDITY = 2
DOOR_OPEN = 3

with_names = {"count": 1, "temp_c": 20.5, "humidity": 41, "door_open": False}
with_numbers = {COUNT: 1, TEMP_C: 20.5, HUMIDITY: 41, DOOR_OPEN: False}

print(len(json.dumps(with_names)))  # 64
print(len(packb(with_names)))       # 41
print(len(packb(with_numbers)))     # 13
```

[`packb_size_comparison.py`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/msgpack/examples/packb_size_comparison.py) runs this comparison in a loop on a changing reading.

## Damaged or untrusted input

`unpackb` raises `ValueError` when the bytes stop short, claim more data than they hold, carry extra bytes after the value, or nest deeper than 8 levels.  A save that a power cut interrupted fails with that error at load, where the alternative would be a different dict.  `packb` refuses nesting deeper than 8 levels too, so `unpackb` reads back everything `packb` packs.

`unpackb` returns the types the bytes hold.  A packed `{"port": "80"}` unpacks with a string where the code expects `{"port": 80}`.  Check the types after unpacking bytes from flash that may be damaged or from a sender outside your control.

The library's own Python decoder makes these checks on CPython, on MicroPython, and on CircuitPython builds without the built-in `msgpack` module.  A CircuitPython board with the built-in module decodes in firmware, which sets no nesting limit.  `unpackb` there still raises `ValueError` for bytes that stop short or carry extra bytes at the end.

## Supported types

| Python type | Notes |
|---|---|
| `None`, `True`, `False` | 1 byte each |
| `int` | −2³¹ to 2³²−1, packed in the fewest bytes that hold it.  CircuitPython's built-in module packs −2³⁰ to 2³⁰−1 and raises `ValueError: no default packer` beyond that. |
| `float` | 32-bit, about 7 significant digits: `1751414400.5` unpacks as `1751414400.0` |
| `str` | UTF-8, up to 65535 bytes |
| `bytes` / `bytearray` | Up to 65535 bytes |
| `list` / `tuple` | A tuple packs as an array and unpacks as a list |
| `dict` | Up to 65535 entries.  Keys can be `None`, `bool`, `int`, `float`, `str`, or `bytes`. |

Any other type raises `TypeError`.  The library's Python encoder raises `OverflowError` for an integer outside its 32-bit range and for a string, bytes, list, or dict past 65535.

## Memory notes

The decoder reads its input through a `memoryview` from start to finish, so slicing the input copies nothing.  Only the `bytes` and `str` values it returns take new memory.

`packb` grows a `bytearray` as it encodes and copies it to `bytes` once at the end.  MicroPython grows a bytearray to close to the size it needs, with 8 bytes of slack per `append`.  The number of reallocations grows with the number of values packed.

### Allocation profile (MicroPython 1.26 unix port, GC disabled)

Each row is the heap one call allocates, so a tick that packs or unpacks needs that much free heap.  Each figure averages 100 calls made between `gc.collect(); gc.disable(); base = gc.mem_alloc()` and a second `gc.mem_alloc()` reading:

| Operation | Payload | Heap alloc per call |
|---|---|---:|
| `packb` settings dict | 47 B (small ints + bools + short strings) | ~544 B |
| `packb` sensor dict | 59 B (5 floats + small int) | ~609 B |
| `packb` long-string config | 263 B (3 strings &gt; 31 bytes each) | ~1 024 B |
| `unpackb` settings dict | 47 B input, 4 string fields | ~609 B |
| `import chumicro_msgpack` (one-time) | n/a | ~15.4 KB |

## Platform notes

| Runtime | What packs and unpacks |
|---|---|
| CircuitPython on a board | The firmware's built-in `msgpack` module, for all four functions.  The library's Python encoder never loads, which saves heap. |
| CircuitPython unix port | The library's Python encoder, because the port has no built-in `msgpack` module. |
| MicroPython | The library's Python encoder.  MicroPython has no built-in `msgpack` module. |
| CPython | The library's Python encoder.  `import msgpack` on CPython finds the PyPI package, which defaults to 64-bit floats and integers.  The library therefore uses a built-in `msgpack` module only when `sys.implementation.name == "circuitpython"`. |

Bytes packed on one runtime unpack on any other, for every value inside the ranges in [Supported types](#supported-types).

## Wire-format compatibility with PyPI `msgpack`

For every value inside [Supported types](#supported-types), `chumicro_msgpack.packb(value)` produces the same bytes as `msgpack.packb(value, use_single_float=True)` from the PyPI package.  A board unpacks with `chumicro_msgpack` what a laptop tool packed with PyPI `msgpack`.

Pass `use_single_float=True` on the laptop.  PyPI `msgpack` packs floats as 64-bit by default: `msgpack.packb(0.5)` writes the tag `0xcb` and 8 bytes.  `chumicro_msgpack.unpackb` on MicroPython and CPython rejects that tag and names it:

```
ValueError: float64 (0xcb) not in chumicro msgpack subset; encode with msgpack.packb(obj, use_single_float=True)
```

CircuitPython's built-in module reads a 64-bit float and keeps it as a 32-bit one.  Ext types fall outside the subset on every runtime.

## Examples

Every example runs until it is stopped, printing as it goes:

| Example | What it shows |
|---|---|
| [`packb_basic.py`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/msgpack/examples/packb_basic.py) | Packs a changing reading once a second, prints the bytes in hex, and unpacks them again |
| [`packb_size_comparison.py`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/msgpack/examples/packb_size_comparison.py) | Measures a reading every two seconds as JSON, as msgpack, and as msgpack with number keys |
| [`stream_roundtrip.py`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/msgpack/examples/stream_roundtrip.py) | Writes a reading into a `BytesIO` stream with `pack` and reads it back with `unpack`, once a second |
| [`circuitpython_nvm_settings.py`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/msgpack/examples/circuitpython_nvm_settings.py) | Saves a settings dict in `microcontroller.nvm` behind a two-byte length once per start, then reads it back every five seconds.  Press reset and the saved setting comes back. |

`packb_basic.py`, `packb_size_comparison.py`, and `stream_roundtrip.py` run on CPython, MicroPython, and CircuitPython.  `circuitpython_nvm_settings.py` needs a CircuitPython board, saved as `code.py` on the CIRCUITPY drive.

---

<div class="chumicro-footer" markdown>

[← Home](index.md)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/msgpack) · \
[PyPI](https://pypi.org/project/chumicro-msgpack/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
