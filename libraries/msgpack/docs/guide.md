# User Guide

## Overview

`chumicro-msgpack` serializes Python objects to compact binary bytes using the [MessagePack](https://msgpack.org) format and deserializes them back.  It covers the subset of msgpack needed on microcontrollers: integers up to 32-bit, 32-bit floats, strings, bytes, booleans, None, lists, tuples, and dicts.

The library exposes four functions: `packb` and `unpackb` for bytes-based encoding/decoding, and `pack` and `unpack` for stream-based I/O.  On CircuitPython boards with the native C `msgpack` module, all four delegate to the built-in — the pure-Python encoder is never loaded.

## When to use msgpack vs `struct`

Python's `struct` module and msgpack both produce compact binary data, but they solve different problems:

| | `struct` | msgpack |
|---|---|---|
| **Schema** | Fixed layout — both sides must agree on a format string (e.g., `">HBf"`) | Self-describing — types are encoded in the data |
| **Flexibility** | Adding or removing a field changes the layout and breaks readers | Dicts and arrays grow naturally; old readers ignore unknown keys |
| **Size** | Smallest possible for a known fixed layout | Slightly larger due to type tags, but still much smaller than JSON |
| **Best for** | Fixed sensor packets, register maps, wire protocols with a spec | Settings dicts, configuration storage, messages between devices that may run different firmware versions |

**Use `struct`** when the data layout is fixed and both sides are compiled together (e.g., a sensor reading struct that never changes).  **Use msgpack** when the data is dict-like, may evolve over time, or when you want to inspect the data without knowing the schema.

## Getting started

```python
from chumicro_msgpack import packb, unpackb

data = packb({"ssid": "MyNetwork", "configured": True})
print(data)          # compact binary bytes

restored = unpackb(data)
print(restored)      # {'ssid': 'MyNetwork', 'configured': True}
```

## Stream-based API (preferred on microcontrollers)

`pack` and `unpack` write to and read from stream objects (anything with `.write()` or `.read()`).  This matches CircuitPython's native `msgpack` API.

When writing to a file, socket, or NVM wrapper, prefer `pack` over `packb` — it writes directly to the destination without building an intermediate `bytes` object in RAM.

```python
from io import BytesIO
from chumicro_msgpack import pack, unpack

buffer = BytesIO()
pack({"key": [1, 2, 3]}, buffer)

buffer.seek(0)
result = unpack(buffer)
print(result)  # {'key': [1, 2, 3]}
```

## Bytes-based API

`packb` and `unpackb` work with `bytes` objects directly.  They are convenient when you need the encoded data in memory — for example, to measure its length before writing it with a framing header, or to pass it to an API that expects `bytes`.

On microcontrollers, be aware that `packb` allocates a temporary `bytearray`, grows it during encoding, then copies it to `bytes`.  For small payloads (typical settings dicts) this is fine.  For larger data or tight loops, prefer the stream-based `pack` to avoid the intermediate allocation.

```python
from chumicro_msgpack import packb, unpackb

# Encode any supported Python object.
packed = packb([1, "hello", None, True])

# Decode from bytes, bytearray, or memoryview.
original = unpackb(packed)
print(original)  # [1, 'hello', None, True]
```

`unpackb` accepts `bytes`, `bytearray`, and `memoryview`, so you can decode directly from a pre-allocated buffer without copying.

## Integer keys for compact storage

When storing settings in NVM or sleep memory, use integer keys instead of strings.  Integer keys encode in 1 byte (vs. multiple bytes for quoted strings), saving space on every entry:

```python
from chumicro_msgpack import packb, unpackb
import json

settings = {0: "MyNetwork", 1: "secret123", 2: "lamp", 3: True}

msgpack_size = len(packb(settings))
json_size = len(json.dumps(settings))

print(f"msgpack: {msgpack_size} bytes")
print(f"JSON:    {json_size} bytes")
# msgpack is significantly smaller
```

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

## Platform notes

| Runtime | What happens |
|---|---|
| CircuitPython (hardware) | Native C `msgpack` module handles all four functions.  The pure-Python encoder (`_pure.py`) is never imported — saves ~700 bytes of heap RAM. |
| CircuitPython (unix port) | Native module is not compiled in; uses the pure-Python encoder. |
| MicroPython | Pure-Python encoder (MicroPython has no built-in msgpack). |
| CPython | Pure-Python encoder (CPython's `msgpack` is a third-party PyPI package, not stdlib). |

The wire format is identical regardless of which implementation is used — data packed on one runtime can be unpacked on any other.

## What's new

<!-- Add entries for user-visible changes when bumping VERSION.
     One bullet per change. Internal refactors don't need entries.
     At stable promotion, collapse/edit as needed. -->

- **0.1.23**: CI and documentation improvements.

---

<div class="chumicro-footer" markdown>

[← Home](index.md)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/msgpack) · [PyPI](https://pypi.org/project/chumicro-msgpack/) · [Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · [Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
