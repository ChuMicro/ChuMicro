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

## Decoding corrupt or untrusted input

`unpackb` is a *trusting* decoder, not a spec validator. It is safe against malformed *framing* — truncated, over-length, or trailing-garbage input, and nesting deeper than 32 levels, all raise `ValueError` instead of returning a silently-wrong value. This matters for flash-backed config and kvstore, where a power-loss-truncated payload must fail loudly rather than decode as a structurally-valid wrong dict.

What it does **not** do is check that a structurally-valid payload has the type shape you expect — a packed `{"port": "80"}` decodes fine when your code wants `{"port": 80}`. Code persisting corruption- or attacker-reachable bytes still owns type-shape validation of what comes back.

Two boundary notes:

- The hardening lives in the pure-Python decoder, which is what runs on CPython, MicroPython, and CircuitPython boards *without* the native `msgpack` module. On CircuitPython boards that ship the native C `msgpack`, decoding goes through the firmware's decoder, whose framing behavior is its own.
- Truncation that lands on a fixed-width primitive or a length prefix surfaces as `ValueError("buffer too small")` (from `struct`) rather than the framing message — still loud, still never a silent short read.

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

## Memory notes

`unpackb` accepts `bytes`, `bytearray`, and `memoryview`, so you can decode directly from a pre-allocated buffer without copying.  Internally the decoder treats the input as a `memoryview` end-to-end — slices stay as views; only the final `bytes` / `str` results are heap allocations.

`packb` builds a `bytearray` that grows as encoding proceeds, then copies to `bytes` once at the end.  MicroPython's bytearray uses capacity-doubling, so a typical settings dict (~50 bytes encoded) goes through ~5 reallocations during the build.

`pack` and `unpack` (stream-based) match the signatures CircuitPython's native C `msgpack` module exposes and delegate to it on hardware that ships it.  On every other runtime — MicroPython, CPython, CircuitPython unix-port — `pack` calls `packb` and writes the result to the stream in one shot; it does **not** stream incrementally.  If you need true streaming on those runtimes, write your own loop around `packb` per element.

### Allocation profile (MicroPython 1.26 unix-port, GC disabled)

Useful when budgeting heap for a tick.  Measured by wrapping each call in `gc.collect(); gc.disable(); base = gc.mem_alloc()` and reading the delta after 100 iterations.

| Operation | Payload | Heap alloc per call |
|---|---|---:|
| `packb` settings dict | 47 B (small ints + bools + short strings) | ~544 B |
| `packb` sensor dict | 59 B (5 floats + small int) | ~609 B |
| `packb` long-string config | 263 B (3 strings &gt; 31 bytes each) | ~1 024 B |
| `unpackb` settings dict | 47 B input, 4 string fields | ~609 B |
| `import chumicro_msgpack` (one-time) | — | ~15.4 KB |

The numbers shift across firmware versions and payload shapes — they're a sanity baseline, not a contract.

## Platform notes

| Runtime | What happens |
|---|---|
| CircuitPython (hardware) | Native C `msgpack` module handles all four functions.  The pure-Python encoder (`_pure.py`) is never imported, keeping heap usage lower on memory-tight boards. |
| CircuitPython (unix port) | Native module is not compiled in; uses the pure-Python encoder. |
| MicroPython | Pure-Python encoder (MicroPython has no built-in msgpack). |
| CPython | Pure-Python encoder (CPython's `msgpack` is a third-party PyPI package, not stdlib). |

The wire format is identical regardless of which implementation is used — data packed on one runtime can be unpacked on any other.

## Wire-format compatibility with PyPI `msgpack`

`chumicro_msgpack.packb(obj)` produces bytes byte-for-byte identical to `msgpack.packb(obj, use_single_float=True)` for any subset-conforming input.  This lets a host-side tool encode with PyPI `msgpack` while the device decodes with `chumicro_msgpack` — same wire format, no conversion step.

The subset is:

* Integers in `[-2**31, 2**32 - 1]`.
* Floats encoded as 32-bit (the `use_single_float=True` flag on the
  PyPI side).
* Strings, bytes, arrays, and maps with sizes under `65_536`.
* No ext types.

The decoder names the offending tag in its `ValueError` if a stricter encoder produces something outside the subset — for example, `"float64 (0xcb) not in chumicro msgpack subset; encode with msgpack.packb(obj, use_single_float=True)"`.  Two sharp edges this avoids:

1. **PyPI's default float encoding is float64.**  Without `use_single_float=True`, `msgpack.packb(0.5)` emits `0xcb` + 8 bytes, which `chumicro_msgpack.unpackb` rejects.
2. **Native delegation is gated to CircuitPython only.**  On CPython, `import msgpack` would resolve to the PyPI package (with a different contract — float64, int64, `strict_map_key`), so `chumicro_msgpack` only delegates to the native C module when `sys.implementation.name == "circuitpython"`.  Other runtimes use the pure-Python encoder bundled in `_pure.py`.

---

<div class="chumicro-footer" markdown>

[← Home](index.md)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/msgpack) · \
[PyPI](https://pypi.org/project/chumicro-msgpack/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
