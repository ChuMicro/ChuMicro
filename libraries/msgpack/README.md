# chumicro-msgpack

<img src="https://raw.githubusercontent.com/ChuMicro/ChuMicro/main/support/docs/chumicro_tip.png"
align="left" width="64" style="margin-right: 16px; margin-bottom: 8px;">

**Turn a dict into a few bytes and back again: the job JSON does, in fewer bytes.**

`packb(reading)` turns a dict, list, number, or string into compact bytes you can save in NVM, write to a file, or send over the network.  `unpackb(data)` turns them back.  The bytes follow the [MessagePack](https://msgpack.org) format, so a laptop reading them with the PyPI `msgpack` package gets the same values.  On a CircuitPython board whose firmware has the built-in `msgpack` module, these functions use it.  The same code runs on CircuitPython, MicroPython, and CPython.

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

[Start here](https://chumicro.com/ChuMicro/guides/start-here/) takes a new board from flashing CircuitPython or MicroPython to running your own blink.  [Installing libraries](https://chumicro.com/ChuMicro/guides/install/) covers registering the bundle, the pre-compiled `.mpy` packages, the experimental channel, and why package names use a hyphen on PyPI and an underscore on the board.

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
| `packb(obj)` | Pack a Python object into MessagePack bytes |
| `unpackb(data)` | Unpack MessagePack `bytes`, `bytearray`, or `memoryview` back into a Python object |

### Streams

| Symbol | Description |
|---|---|
| `pack(obj, stream)` | Pack an object and write it to anything with a `write()` method, such as a file or socket |
| `unpack(stream)` | Read one packed object back from anything with a `read()` method |

Use `packb` and `unpackb` to hold the bytes in hand: to save them in NVM, to measure their length, or to put a header in front.  Use `pack` and `unpack` to write straight to a file or socket.  On a CircuitPython board with the built-in module, `pack` writes as it encodes.  Everywhere else it packs to bytes first and then writes them.

### Supported types

| Python type | MessagePack format | Limit |
|---|---|---|
| `None` | nil | none |
| `True` / `False` | bool | none |
| `int` | fixint, int8/16/32, uint8/16/32 | `-2^31 ≤ value ≤ 2^32 − 1` |
| `float` | float32 | single precision, about 7 decimal digits |
| `str` | fixstr, str8, str16 | up to 65 535 bytes UTF-8 |
| `bytes` / `bytearray` | bin8, bin16 | up to 65 535 bytes |
| `list` / `tuple` | fixarray, array16 | up to 65 535 elements |
| `dict` | fixmap, map16 | up to 65 535 entries |

On MicroPython and CPython, packing a value outside these limits raises `OverflowError`.  Unpacking a format outside this table, such as `float64` (`0xcb`), `int64` (`0xd3`), `uint64` (`0xcf`), or a `*32`-length variant, raises a `ValueError` that names the format byte.  On a CircuitPython board, the built-in module packs integers from `-2^30` to `2^30 − 1` and raises `ValueError` for a larger integer or a type it cannot pack.

A `tuple` comes back as a `list`, because MessagePack has no tuple type.  A `dict` key may be any supported type, including `int`.  Extension types, such as timestamps and custom classes, are unsupported in both directions.

## Where this fits

Needs no other library.  [`chumicro-config`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/config) uses it to read `/runtime_config.msgpack` on the board, and [`chumicro-kvstore`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/kvstore) uses it to save its values.

## Platform support

Works on CPython, MicroPython, and CircuitPython.

| Runtime | Implementation |
|---|---|
| CircuitPython board | The firmware's built-in `msgpack` module.  The pure-Python code never loads |
| CircuitPython unix port | The pure-Python code, because the port leaves the built-in module out |
| MicroPython | The pure-Python code |
| CPython | The pure-Python code |

### Reading and writing on a laptop

| Writer | Reader | Result |
|---|---|---|
| A board | A laptop with PyPI `msgpack` | Works.  The bytes follow the MessagePack spec, so any reader decodes them |
| A board | A board | Works |
| A laptop with PyPI `msgpack`, inside the supported types | A board | Works when the laptop packs with `use_single_float=True` |
| A laptop with PyPI `msgpack` defaults | A MicroPython board | Fails on floats.  PyPI `msgpack` packs floats as 64-bit by default.  MicroPython refuses them, and a CircuitPython board's built-in module reads them as 32-bit floats |
| A CircuitPython board, with nesting deeper than 8 levels | MicroPython or CPython | Fails.  CircuitPython's built-in module has no nesting limit, and the pure-Python reader refuses depth past 8.  Data saved in NVM on a CircuitPython board fails to load after that board is reflashed to MicroPython, so keep saved data within 8 levels |

A laptop script writes bytes a board can read with this recipe:

```python
import msgpack  # the PyPI package

data = msgpack.packb(obj, use_single_float=True)
# Keep ints in [-2**31, 2**32-1] and lengths under 65 536.
```

`use_single_float=True` switches PyPI `msgpack` from `float64` to `float32`, which every board reads.  `chumicro-workspace` uses the same setting when it writes `/runtime_config.msgpack` for a board.

## Examples

| Example | What it shows |
|---|---|
| [`packb_basic.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/msgpack/examples/packb_basic.py) | Packs a changing reading once a second, prints the bytes, and unpacks them again |
| [`packb_size_comparison.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/msgpack/examples/packb_size_comparison.py) | Measures a reading every two seconds as JSON (64 bytes), MessagePack (41 bytes), and MessagePack with number keys (13 bytes) |
| [`stream_roundtrip.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/msgpack/examples/stream_roundtrip.py) | Writes a reading into a `BytesIO` stream with `pack` and reads it back with `unpack`, once a second |
| [`circuitpython_nvm_settings.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/msgpack/examples/circuitpython_nvm_settings.py) | Saves a settings dict in `microcontroller.nvm` once per start and reads it back every five seconds.  Press reset to see it survive.  CircuitPython board |

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
