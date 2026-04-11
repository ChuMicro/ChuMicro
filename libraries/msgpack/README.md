# chumicro-msgpack

<img src="https://raw.githubusercontent.com/ChuMicro/ChuMicro/main/support/docs/chumicro_tip.png" align="left" width="64" style="margin-right: 16px; margin-bottom: 8px;">

**Compact [MessagePack](https://msgpack.org) serialization — much smaller than JSON.**

Turns Python dicts, lists, and values into binary bytes, typically 30–50% smaller than JSON. Good for NVM storage, serial protocols, and anywhere bytes matter. On CircuitPython boards with the native `msgpack` C module, everything delegates to the built-in — the pure-Python code is never loaded, saving ~700 bytes of heap.

<br clear="left">

> Part of the [ChuMicro](https://github.com/ChuMicro/ChuMicro) family — small, focused Python libraries for microcontrollers and laptops. [See all libraries.](https://github.com/ChuMicro/ChuMicro#whats-in-the-box)

Works on CircuitPython, MicroPython, and CPython.

## Installation

### CircuitPython ([circup](https://github.com/adafruit/circup))

circup is CircuitPython's package manager — it uses bundles to find third-party packages. Register the ChuMicro bundle once, then install by name:

```bash
circup bundle-add ChuMicro/ChuMicro-Bundle
circup install chumicro-msgpack
```

### MicroPython ([mip](https://docs.micropython.org/en/latest/reference/packages.html))

```bash
mpremote mip install github:ChuMicro/ChuMicro-Bundle/chumicro_msgpack
```

### CPython (pip)

```bash
pip install chumicro-msgpack
```

<details>
<summary>Experimental (pre-release) versions and channel switching</summary>

Pre-release builds are published automatically when a library version is bumped.  Do not register both bundles simultaneously — circup may pick either version for a given package.

```bash
# CircuitPython — switch to experimental
circup bundle-remove ChuMicro/ChuMicro-Bundle              # skip if never added
circup bundle-add ChuMicro/ChuMicro-Bundle-Experimental
circup install chumicro-msgpack

# MicroPython
mpremote mip install github:ChuMicro/ChuMicro-Bundle-Experimental/chumicro_msgpack

# CPython
pip install chumicro-msgpack-experimental
```

</details>

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


## Examples

| Example | What it shows |
|---|---|
| `packb_basic.py` | Pack and unpack a settings dict |
| `packb_size_comparison.py` | Compare msgpack vs JSON size for the same dict |
| `stream_roundtrip.py` | Use the stream-based `pack` / `unpack` API with `BytesIO` |
| `circuitpython_nvm_settings.py` | Store and load settings in non-volatile memory (hardware) |

## Docs

📖 **[Stable docs](https://chumicro.github.io/ChuMicro/msgpack/stable/)** · **[Experimental docs](https://chumicro.github.io/ChuMicro/msgpack/experimental/)**

## Find this library

- **PyPI:** [chumicro-msgpack](https://pypi.org/project/chumicro-msgpack/)
- **Bundle:** [ChuMicro-Bundle](https://github.com/ChuMicro/ChuMicro-Bundle/tree/main/chumicro_msgpack) (CircuitPython & MicroPython)
- **Experimental bundle:** [ChuMicro-Bundle-Experimental](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental/tree/main/chumicro_msgpack)
- **Source:** [libraries/msgpack](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/msgpack)
