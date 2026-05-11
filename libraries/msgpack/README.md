# chumicro-msgpack

<img src="https://raw.githubusercontent.com/ChuMicro/ChuMicro/main/support/docs/chumicro_tip.png"
align="left" width="64" style="margin-right: 16px; margin-bottom: 8px;">

**Binary serialization that's typically 30–50 % smaller than JSON.**

The subset of [MessagePack](https://msgpack.org) that fits on a 256 KB board — 32-bit ints, single-precision floats, 16-bit lengths.  Wire-compatible with the PyPI `msgpack` library when it's configured for the same subset (`use_single_float=True`); on CircuitPython firmware that ships the native `msgpack` C module, encoding and decoding delegate to the C path automatically.

<br clear="left">

> Part of the [ChuMicro](https://github.com/ChuMicro/ChuMicro) family — small, focused Python libraries for microcontrollers and laptops. [Browse all libraries.](https://github.com/ChuMicro/ChuMicro/tree/main/libraries)

## Install

```bash
# CircuitPython (after `circup bundle-add ChuMicro/ChuMicro-Bundle`)
circup install chumicro-msgpack

# MicroPython
mpremote mip install github:ChuMicro/ChuMicro-Bundle/chumicro_msgpack

# CPython
pip install chumicro-msgpack
```

For bundle setup, pre-compiled `.mpy` bundles, the experimental channel, and details on PyPI naming, see the [chumicro INSTALL guide](https://github.com/ChuMicro/ChuMicro/blob/main/INSTALL.md).

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

| Python type | msgpack format | Limit |
|---|---|---|
| `None` | nil | — |
| `True` / `False` | bool | — |
| `int` | fixint, int8/16/32, uint8/16/32 | `-2^31 ≤ value ≤ 2^32 − 1` |
| `float` | float32 | single precision (~7 decimal digits) |
| `str` | fixstr, str8, str16 | up to 65 535 bytes UTF-8 |
| `bytes` / `bytearray` | bin8, bin16 | up to 65 535 bytes |
| `list` / `tuple` | fixarray, array16 | up to 65 535 elements |
| `dict` | fixmap, map16 | up to 65 535 entries |

Values outside these limits raise `OverflowError` on encode. Tags outside the subset (`float64` `0xcb`, `int64` `0xd3`, `uint64` `0xcf`, the `*32`-length variants) raise a descriptive `ValueError` on decode that names the offending tag.

`tuple` decodes back as `list` — msgpack has no tuple type. `dict` keys may be any supported type, including `int` (no `strict_map_key` enforcement). Ext types (timestamps, custom classes) are not supported in either direction.

## Cross-runtime compatibility

| Direction | Works? | Notes |
|---|---|---|
| chumicro device writes → host reads | ✓ always | Bytes are spec-compliant; any standard reader decodes them |
| chumicro device writes → chumicro device reads | ✓ always | The common case; full round-trip |
| Host writes with PyPI `msgpack` → chumicro device reads | ✓ if host stays in subset | See recipe below |
| Host writes default PyPI `msgpack` → chumicro device reads | ✗ | PyPI defaults to `float64`, decodes raise on device |

**Host-side recipe** — when a host script needs to produce bytes a chumicro device will read:

```python
import msgpack  # standard PyPI library
data = msgpack.packb(obj, use_single_float=True)
# Caller's job: keep ints in [-2**31, 2**32-1] and lengths under 65 536.
```

`use_single_float=True` switches PyPI msgpack from `float64` to `float32`, matching what chumicro reads.  This is what [`chumicro-workspace`](../../workbench/workspace) uses to write `runtime_config.msgpack` for the device.

## Where this fits

Leaf — no upstream ChuMicro deps.  Used directly by [`chumicro-config`](../config/) to decode `/runtime_config.msgpack` on the device, and by host-side workspace tooling to write it.

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

## Contributing

Working on `chumicro-msgpack` itself?  Clone the [mono-repo](https://github.com/ChuMicro/ChuMicro) if you haven't already — the rest of the workflow assumes you're inside that workspace.

```bash
pip install -e .[test]
pytest tests/                  # host-side tests
pytest functional_tests/       # on-device tests (needs a board registered in devices.yml)
```

Register a board before running functional tests: `chumicro-workspace add-device <id> --address <port>`.

## Docs

📖 **[Stable docs](https://chumicro.github.io/ChuMicro/msgpack/stable/)** · **[Experimental docs](https://chumicro.github.io/ChuMicro/msgpack/experimental/)**

## Find this library

- **PyPI:** [chumicro-msgpack](https://pypi.org/project/chumicro-msgpack/)
- **Bundle:** [ChuMicro-Bundle](https://github.com/ChuMicro/ChuMicro-Bundle/tree/main/chumicro_msgpack) (CircuitPython & MicroPython)
- **Experimental bundle:** [ChuMicro-Bundle-Experimental](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental/tree/main/chumicro_msgpack)
- **Source:** [libraries/msgpack](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/msgpack)

## License

[MIT](https://github.com/ChuMicro/ChuMicro/blob/main/LICENSE)
