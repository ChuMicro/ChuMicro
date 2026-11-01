---
title: "chumicro-msgpack: MessagePack for CircuitPython and MicroPython"
---

# chumicro-msgpack

**Turn a dict into a few bytes and back again: the job JSON does, in fewer bytes.**

`packb(reading)` turns a dict, list, number, or string into compact bytes you can save in NVM, write to a file, or send over the network.  `unpackb(data)` turns them back.  The bytes follow the [MessagePack](https://msgpack.org) format, so a laptop reading them with the PyPI `msgpack` package gets the same values.  On a CircuitPython board whose firmware has the built-in `msgpack` module, these functions use it.  The same code runs on CircuitPython, MicroPython, and CPython.

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

## Documentation

- [User Guide](guide.md): the bytes and stream functions, when to reach for msgpack instead of `struct`, number keys for smaller data, damaged or untrusted input, the supported types, and reading board data on a laptop
- [API Reference](api.md): `packb` and `unpackb` for bytes, `pack` and `unpack` for streams

---

<div class="chumicro-footer" markdown>

[← All ChuMicro Libraries](../../)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/msgpack) · \
[PyPI](https://pypi.org/project/chumicro-msgpack/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
