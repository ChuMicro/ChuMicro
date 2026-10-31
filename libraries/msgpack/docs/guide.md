# User Guide

## Overview

`chumicro-msgpack` turns Python values into compact bytes and back, using the [MessagePack](https://msgpack.org) format.  It does the job `json.dumps` and `json.loads` do, in fewer bytes, which matters when the bytes go into a few kilobytes of NVM or over a slow radio link.  It handles `None`, `bool`, integers up to 32 bits, 32-bit floats, `str`, `bytes`, and lists, tuples, and dicts of those.

Four functions cover it: `packb` and `unpackb` work with bytes in memory, and `pack` and `unpack` write to and read from a stream such as a file or socket.  On a CircuitPython board whose firmware has the built-in `msgpack` module, all four use it and the library's own Python encoder never loads.

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

## When to use msgpack vs `struct`

Python's `struct` module and msgpack both produce compact binary data, but they solve different problems:

| | `struct` | msgpack |
|---|---|---|
| **Schema** | Fixed layout: both sides must agree on a format string (e.g., `">HBf"`) | Self-describing: types are encoded in the data |
| **Flexibility** | Adding or removing a field changes the layout and breaks readers | Dicts and arrays grow naturally; old readers ignore unknown keys |
| **Size** | Smallest possible for a known fixed layout | Slightly larger due to type tags, but still much smaller than JSON |
| **Best for** | Fixed sensor packets, register maps, wire protocols with a spec | Settings dicts, configuration storage, messages between devices that may run different firmware versions |

**Use `struct`** when the data layout is fixed and both sides are compiled together (e.g., a sensor reading struct that never changes).  **Use msgpack** when the data is dict-like, may evolve over time, or when you want to inspect the data without knowing the schema.

## Bytes: `packb` and `unpackb`

`packb` returns the packed data as `bytes`, and `unpackb` takes it back.  Reach for them when you want the bytes in hand: to save them in NVM, to measure their length before writing a header in front, or to pass them to a function that takes `bytes`.

```python
from chumicro_msgpack import packb, unpackb

packed = packb([1, "hello", None, True])
print(unpackb(packed))  # [1, 'hello', None, True]
```

`unpackb` accepts `bytes`, `bytearray`, and `memoryview`, so you can unpack straight from a buffer you already have without copying it first.  `packb` builds the result in a growing `bytearray` and copies it to `bytes` at the end, which costs nothing worth counting for a settings dict.

## Streams: `pack` and `unpack`

`pack(value, stream)` packs a value and writes it to anything with a `write()` method, and `unpack(stream)` reads it back from anything with a `read()` method.  They match the functions of the same name in CircuitPython's built-in `msgpack` module.

```python
from io import BytesIO

from chumicro_msgpack import pack, unpack

stream = BytesIO()
pack({"key": [1, 2, 3]}, stream)

stream.seek(0)
print(unpack(stream))  # {'key': [1, 2, 3]}
```

Write one value per stream.  On MicroPython and CPython, `unpack` reads everything left in the stream and raises `ValueError` if bytes remain after the first value.  On a CircuitPython board with the built-in module, `pack` writes as it encodes; everywhere else it calls `packb` and writes the result, so it saves no memory there.

## Number keys for smaller data

A string key costs one byte per character plus one, so `"humidity"` takes nine bytes every time you pack it.  A small integer key from 0 to 127 takes one.  When space is tight, as in NVM, give each field a number and name the numbers with constants so the code stays readable:

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

`unpackb` raises `ValueError` instead of returning a wrong value when the bytes stop short, claim more data than they hold, carry extra bytes after the value, or nest deeper than 8 levels.  A save that a power cut interrupted therefore fails loudly instead of loading as a different dict.  `packb` refuses nesting deeper than 8 levels too, so anything it packs, `unpackb` reads back.

`unpackb` does not check that the values have the types your code expects: a packed `{"port": "80"}` unpacks without complaint when your code wants `{"port": 80}`.  Check the types yourself when the bytes come from flash that may be damaged or from a sender you do not trust.

These checks belong to the library's own Python decoder, which runs on CPython, MicroPython, and CircuitPython boards without the built-in `msgpack` module.  A CircuitPython board with the built-in module decodes with the firmware instead, which sets no nesting limit; `unpackb` still raises `ValueError` there for bytes that stop short or carry extra bytes at the end.

## Supported types

| Python type | Notes |
|---|---|
| `None`, `True`, `False` | 1 byte each |
| `int` | −2³¹ to 2³²−1; uses the smallest encoding automatically |
| `float` | 32-bit (float32); limited precision compared to CPython's 64-bit float |
| `str` | UTF-8 encoded; up to 65535 bytes |
| `bytes` / `bytearray` | Up to 65535 bytes |
| `list` / `tuple` | Tuples encode as arrays; decoding always returns lists |
| `dict` | Up to 65535 entries; keys can be any supported type |

Unsupported types raise `TypeError`.  Integers outside the 32-bit range raise `OverflowError`.

## Memory notes

The decoder reads its input through a `memoryview` from start to finish, so slicing the input copies nothing; only the `bytes` and `str` values it returns take new memory.

`packb` grows a `bytearray` as it encodes and copies it to `bytes` once at the end.  MicroPython grows a bytearray close to the exact size needed (an `append` adds 8 bytes of slack), so the number of reallocations grows with the number of values packed.

### Allocation profile (MicroPython 1.26 unix-port, GC disabled)

Useful when budgeting heap for a tick.  Measured by wrapping each call in `gc.collect(); gc.disable(); base = gc.mem_alloc()` and reading the delta after 100 iterations.

| Operation | Payload | Heap alloc per call |
|---|---|---:|
| `packb` settings dict | 47 B (small ints + bools + short strings) | ~544 B |
| `packb` sensor dict | 59 B (5 floats + small int) | ~609 B |
| `packb` long-string config | 263 B (3 strings &gt; 31 bytes each) | ~1 024 B |
| `unpackb` settings dict | 47 B input, 4 string fields | ~609 B |
| `import chumicro_msgpack` (one-time) | n/a | ~15.4 KB |

Other firmware versions and other payloads give different numbers; use these to judge the scale of the cost.

## Platform notes

| Runtime | What happens |
|---|---|
| CircuitPython (hardware) | Native C `msgpack` module handles all four functions.  The pure-Python encoder (`_pure.py`) is never imported, keeping heap usage lower on memory-tight boards. |
| CircuitPython (unix port) | Native module is not compiled in; uses the pure-Python encoder. |
| MicroPython | Pure-Python encoder (MicroPython has no built-in msgpack). |
| CPython | Pure-Python encoder (CPython's `msgpack` is a third-party PyPI package, not stdlib). |

The wire format is identical regardless of which implementation is used: data packed on one runtime can be unpacked on any other.

## Wire-format compatibility with PyPI `msgpack`

`chumicro_msgpack.packb(obj)` produces bytes byte-for-byte identical to `msgpack.packb(obj, use_single_float=True)` for any subset-conforming input.  This lets a host-side tool encode with PyPI `msgpack` while the device decodes with `chumicro_msgpack`: same wire format, no conversion step.

The subset is:

* Integers in `[-2**31, 2**32 - 1]`.
* Floats encoded as 32-bit (the `use_single_float=True` flag on the
  PyPI side).
* Strings, bytes, arrays, and maps with sizes under `65_536`.
* No ext types.

The decoder names the offending tag in its `ValueError` if a stricter encoder produces something outside the subset, for example `"float64 (0xcb) not in chumicro msgpack subset; encode with msgpack.packb(obj, use_single_float=True)"`.  Two sharp edges this avoids:

1. **PyPI's default float encoding is float64.**  Without `use_single_float=True`, `msgpack.packb(0.5)` emits `0xcb` + 8 bytes, which `chumicro_msgpack.unpackb` rejects on MicroPython and CPython.  A CircuitPython board's built-in module reads it as a 32-bit float.
2. **Native delegation is gated to CircuitPython only.**  On CPython, `import msgpack` would resolve to the PyPI package (with a different contract: float64, int64, `strict_map_key`), so `chumicro_msgpack` only delegates to the native C module when `sys.implementation.name == "circuitpython"`.  Other runtimes use the pure-Python encoder bundled in `_pure.py`.

## Examples

Every example in the [examples](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/msgpack/examples) directory runs until you stop it, printing as it goes:

| Example | What it shows |
|---|---|
| `packb_basic.py` | Packs a changing reading once a second, prints the bytes in hex, and unpacks them again |
| `packb_size_comparison.py` | Measures a reading every two seconds as JSON, as msgpack, and as msgpack with number keys |
| `stream_roundtrip.py` | Writes a reading into a `BytesIO` stream with `pack` and reads it back with `unpack`, once a second |
| `circuitpython_nvm_settings.py` | Saves a settings dict in `microcontroller.nvm` behind a two-byte length once per start, then reads it back every five seconds; press reset to see the setting survive |

`packb_basic.py`, `packb_size_comparison.py`, and `stream_roundtrip.py` run on CPython, MicroPython, and CircuitPython.  `circuitpython_nvm_settings.py` needs a CircuitPython board; save it as `code.py` on the CIRCUITPY drive.

---

<div class="chumicro-footer" markdown>

[← Home](index.md)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/msgpack) · \
[PyPI](https://pypi.org/project/chumicro-msgpack/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
