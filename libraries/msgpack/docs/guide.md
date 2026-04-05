# User Guide

## Overview

`chumicro-msgpack` serializes Python objects to compact binary bytes using the [MessagePack](https://msgpack.org) format and deserializes them back.  It covers the subset of msgpack needed on microcontrollers: integers up to 32-bit, 32-bit floats, strings, bytes, booleans, None, lists, tuples, and dicts.

The library exposes four functions: `packb` and `unpackb` for bytes-based encoding/decoding, and `pack` and `unpack` for stream-based I/O.  On CircuitPython boards with the native C `msgpack` module, all four delegate to the built-in — the pure-Python encoder is never loaded.

## Getting started

```python
from chumicro_msgpack import packb, unpackb

data = packb({"ssid": "MyNetwork", "configured": True})
print(data)          # compact binary bytes

restored = unpackb(data)
print(restored)      # {'ssid': 'MyNetwork', 'configured': True}
```

## Bytes-based API

`packb` and `unpackb` are the most common entry points.  They work with `bytes` objects directly — no streams needed.

```python
from chumicro_msgpack import packb, unpackb

# Encode any supported Python object.
packed = packb([1, "hello", None, True])

# Decode from bytes, bytearray, or memoryview.
original = unpackb(packed)
print(original)  # [1, 'hello', None, True]
```

`unpackb` accepts `bytes`, `bytearray`, and `memoryview`, so you can decode directly from a pre-allocated buffer without copying.

## Stream-based API

`pack` and `unpack` write to and read from stream objects (anything with `.write()` or `.read()`).  This matches CircuitPython's native `msgpack` API.

```python
from io import BytesIO
from chumicro_msgpack import pack, unpack

buffer = BytesIO()
pack({"key": [1, 2, 3]}, buffer)

buffer.seek(0)
result = unpack(buffer)
print(result)  # {'key': [1, 2, 3]}
```

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
