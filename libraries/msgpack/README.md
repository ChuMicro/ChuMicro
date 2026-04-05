# chumicro-msgpack

Cross-runtime [MessagePack](https://msgpack.org) serialization for CircuitPython, MicroPython, and CPython.

Encodes Python objects to compact binary bytes and decodes them back.  Supports the subset of msgpack needed for embedded use: integers (up to 32-bit), floats (32-bit), strings, bytes, booleans, None, lists, tuples, and dicts.

On CircuitPython boards with the native `msgpack` C module, all functions delegate to the built-in — the pure-Python encoder is never loaded, saving ~700 bytes of heap RAM.

## Installation

```bash
# CPython (pip)
pip install chumicro-msgpack

# CircuitPython (circup)
circup bundle-add ChuMicro/chumicro-bundle
circup install chumicro-msgpack

# MicroPython (mip)
mpremote mip install github:ChuMicro/chumicro-bundle/chumicro_msgpack
```

For experimental (pre-release) versions from the develop branch:

```bash
pip install chumicro-msgpack-experimental
circup bundle-add ChuMicro/chumicro-bundle-experimental
circup install chumicro-msgpack-experimental
mpremote mip install github:ChuMicro/chumicro-bundle-experimental/chumicro_msgpack_experimental
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

### Stream-based API (preferred on microcontrollers)

| Symbol | Description |
|---|---|
| `pack(obj, stream)` | Pack an object directly to a writable stream — no intermediate buffer |
| `unpack(stream)` | Unpack one object from a readable stream |

### Bytes-based API

| Symbol | Description |
|---|---|
| `packb(obj)` | Pack a Python object to msgpack bytes (allocates a temporary buffer) |
| `unpackb(data)` | Unpack msgpack bytes (bytes, bytearray, or memoryview) to a Python object |

Use `pack`/`unpack` when writing to files, sockets, or NVM.  Use `packb`/`unpackb` when you need the encoded bytes in memory (e.g., to measure length before framing).

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
