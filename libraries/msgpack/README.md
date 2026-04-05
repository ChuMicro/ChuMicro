# chumicro-msgpack

Cross-runtime [MessagePack](https://msgpack.org) serialization for CircuitPython, MicroPython, and CPython.

Encodes Python objects to compact binary bytes and decodes them back.  Supports the subset of msgpack needed for embedded use: integers (up to 32-bit), floats (32-bit), strings, bytes, booleans, None, lists, tuples, and dicts.

On CircuitPython boards with the native `msgpack` C module, all functions delegate to the built-in — the pure-Python encoder is never loaded, saving ~700 bytes of heap RAM.

## Installation

```bash
# CPython (pip)
pip install chumicro-msgpack

# CircuitPython (circup) — coming soon
# circup install chumicro-msgpack

# MicroPython (mip) — coming soon
# import mip; mip.install("chumicro-msgpack")
```

## Quick example

```python
from chumicro_msgpack import packb, unpackb

settings = {0: "MyNetwork", 1: "secret", 2: True}

data = packb(settings)       # compact binary bytes
print(len(data))             # much smaller than JSON

restored = unpackb(data)
print(restored)              # {0: 'MyNetwork', 1: 'secret', 2: True}
```

## What's included

### Bytes-based API

| Symbol | Description |
|---|---|
| `packb(obj)` | Pack a Python object to msgpack bytes |
| `unpackb(data)` | Unpack msgpack bytes (bytes, bytearray, or memoryview) to a Python object |

### Stream-based API

| Symbol | Description |
|---|---|
| `pack(obj, stream)` | Pack an object to a writable stream |
| `unpack(stream)` | Unpack one object from a readable stream |

### Supported types

| Python type | msgpack format |
|---|---|
| `None` | nil |
| `True` / `False` | bool |
| `int` (−2³¹ to 2³²−1) | fixint, int8/16/32, uint8/16/32 |
| `float` | float32 |
| `str` | fixstr, str8, str16 |
| `bytes` / `bytearray` | bin8, bin16 |
| `list` / `tuple` | fixarray, array16 |
| `dict` | fixmap, map16 |

64-bit integers and floats are not supported, matching CircuitPython's built-in limitation.

## Platform support

| Runtime | Implementation |
|---|---|
| CircuitPython (hardware) | Delegates to the native C `msgpack` module; pure-Python code is never loaded |
| CircuitPython (unix port) | Pure-Python encoder/decoder (native module not compiled in) |
| MicroPython | Pure-Python encoder/decoder |
| CPython | Pure-Python encoder/decoder |

## Docs

- [User guide](docs/guide.md) — getting started, usage patterns, size comparison
- [API reference](docs/api.md) — full API documentation

## Examples

| Example | What it shows |
|---|---|
| `packb_basic.py` | Pack and unpack a settings dict |
| `packb_size_comparison.py` | Compare msgpack vs JSON size for the same dict |
| `stream_roundtrip.py` | Use the stream-based `pack` / `unpack` API with `BytesIO` |
| `circuitpython_nvm_settings.py` | Store and load settings in non-volatile memory (hardware) |
