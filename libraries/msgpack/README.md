# chumicro-msgpack

<img src="https://raw.githubusercontent.com/ChuMicro/ChuMicro/main/support/docs/chumicro_tip.png"
align="left" width="64" style="margin-right: 16px; margin-bottom: 8px;">

**Turn a dict into a few bytes and back again: the job JSON does, in fewer bytes.**

`packb(reading)` turns a dict, list, number, or string into compact bytes you can save in NVM, write to a file, or send over the network, and `unpackb(data)` turns them back.  The bytes follow the [MessagePack](https://msgpack.org) format, so a laptop reading them with the PyPI `msgpack` package gets the same values.  On a CircuitPython board whose firmware has the built-in `msgpack` module, these functions use it.

The library covers the part of MessagePack that suits a small board: integers up to 32 bits, 32-bit floats, strings and bytes up to 65,535 bytes, and lists and dicts up to 65,535 items.

<br clear="left">

> Part of the [ChuMicro](https://github.com/ChuMicro/ChuMicro) family: small, focused Python libraries for microcontrollers and laptops. [Browse all libraries.](https://github.com/ChuMicro/ChuMicro/tree/main/libraries)

## Install

```bash
# CircuitPython (after `circup bundle-add ChuMicro/ChuMicro-Bundle`)
circup install chumicro_msgpack

# MicroPython
mpremote mip install github:ChuMicro/ChuMicro-Bundle/chumicro_msgpack

# CPython
pip install chumicro-msgpack
```

For bundle setup, pre-compiled `.mpy` bundles, the experimental channel, and details on PyPI naming, see the [ChuMicro install guide](https://chumicro.com/ChuMicro/guides/install/).

## Quick example

Pack a changing sensor reading once a second and print the bytes:

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

The same reading as JSON text takes 28 bytes.

## What's included

### Bytes

| Symbol | Description |
|---|---|
| `packb(obj)` | Pack a Python object into msgpack bytes |
| `unpackb(data)` | Unpack msgpack `bytes`, `bytearray`, or `memoryview` back into a Python object |

### Streams

| Symbol | Description |
|---|---|
| `pack(obj, stream)` | Pack an object and write it to anything with a `write()` method, such as a file or socket |
| `unpack(stream)` | Read one packed object back from anything with a `read()` method |

Use `packb` and `unpackb` when you want the bytes in hand: to save them in NVM, to measure their length, or to put a header in front.  Use `pack` and `unpack` to write straight to a file or socket.  On a CircuitPython board with the built-in module, `pack` writes as it encodes; everywhere else it packs to bytes first and then writes them.

### Supported types

| Python type | msgpack format | Limit |
|---|---|---|
| `None` | nil | none |
| `True` / `False` | bool | none |
| `int` | fixint, int8/16/32, uint8/16/32 | `-2^31 ≤ value ≤ 2^32 − 1` |
| `float` | float32 | single precision (~7 decimal digits) |
| `str` | fixstr, str8, str16 | up to 65 535 bytes UTF-8 |
| `bytes` / `bytearray` | bin8, bin16 | up to 65 535 bytes |
| `list` / `tuple` | fixarray, array16 | up to 65 535 elements |
| `dict` | fixmap, map16 | up to 65 535 entries |

Values outside these limits raise `OverflowError` on encode. Tags outside the subset (`float64` `0xcb`, `int64` `0xd3`, `uint64` `0xcf`, the `*32`-length variants) raise a descriptive `ValueError` on decode that names the offending tag.

`tuple` decodes back as `list`, since msgpack has no tuple type. `dict` keys may be any supported type, including `int` (no `strict_map_key` enforcement). Ext types (timestamps, custom classes) are not supported in either direction.

## Cross-runtime compatibility

| Direction | Works? | Notes |
|---|---|---|
| chumicro device writes → host reads | ✓ always | Bytes are spec-compliant; any standard reader decodes them |
| chumicro device writes → chumicro device reads | ✓ always | The common case; full round-trip |
| Host writes with PyPI `msgpack` → chumicro device reads | ✓ if host stays in subset | See recipe below |
| Host writes default PyPI `msgpack` → chumicro device reads | ✗ for floats on MicroPython | PyPI packs floats as 64-bit by default.  MicroPython refuses them; a CircuitPython board's built-in module reads them as 32-bit floats |
| CircuitPython firmware codec writes deep nesting → pure-path reads | ✗ past 8 levels | CircuitPython boards resolve `packb` to the firmware's native `msgpack`, which has no nesting cap; the pure path (MicroPython, CPython) refuses depth past 8 on decode.  A payload nested deeper than 8 persisted on a CircuitPython board (NVM, littlefs) will not load after reflashing that board to MicroPython; keep persisted structures within 8 levels |

**Host-side recipe**, when a host script needs to produce bytes a chumicro device will read:

```python
import msgpack  # standard PyPI library
data = msgpack.packb(obj, use_single_float=True)
# Caller's job: keep ints in [-2**31, 2**32-1] and lengths under 65 536.
```

`use_single_float=True` switches PyPI msgpack from `float64` to `float32`, matching what chumicro reads.  This is what `chumicro-workspace` does when it writes `runtime_config.msgpack` for the device.

## Where this fits

Needs no other ChuMicro library.  [`chumicro-config`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/config) uses it to read `/runtime_config.msgpack` on the board, and [`chumicro-kvstore`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/kvstore) uses it to save its values.  `chumicro-workspace` writes `runtime_config.msgpack` on your laptop with the PyPI `msgpack` package, using the recipe above.

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
| [`packb_basic.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/msgpack/examples/packb_basic.py) | Packs a changing reading once a second, prints the bytes, and unpacks them again |
| [`packb_size_comparison.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/msgpack/examples/packb_size_comparison.py) | Measures a reading every two seconds as JSON (64 bytes), msgpack (41 bytes), and msgpack with number keys (13 bytes) |
| [`stream_roundtrip.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/msgpack/examples/stream_roundtrip.py) | Writes a reading into a `BytesIO` stream with `pack` and reads it back with `unpack`, once a second |
| [`circuitpython_nvm_settings.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/msgpack/examples/circuitpython_nvm_settings.py) | Saves a settings dict in `microcontroller.nvm` once per start and reads it back every five seconds; press reset to see it survive (CircuitPython board) |

## Contributing

Issues, bug reports, and pull requests are welcome, and so is "I ran it on this board and here's what happened", some of the most useful feedback a hardware project can get.  Development happens in the [ChuMicro repository](https://github.com/ChuMicro/ChuMicro), whose contributing guide covers setup and the test workflow.

## Docs

📖 **[Stable docs](https://chumicro.com/ChuMicro/msgpack/stable/)** · **[Experimental docs](https://chumicro.com/ChuMicro/msgpack/experimental/)**

## Find this library

- **PyPI:** [chumicro-msgpack](https://pypi.org/project/chumicro-msgpack/)
- **Bundle:** [ChuMicro-Bundle](https://github.com/ChuMicro/ChuMicro-Bundle/tree/main/chumicro_msgpack) (CircuitPython & MicroPython)
- **Experimental bundle:** [ChuMicro-Bundle-Experimental](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental/tree/main/chumicro_msgpack)
- **Source:** [libraries/msgpack](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/msgpack)

## License

[MIT](https://github.com/ChuMicro/ChuMicro/blob/main/LICENSE)
