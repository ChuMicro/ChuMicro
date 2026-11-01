---
title: "chumicro-kvstore: storage that survives a reboot on CircuitPython and MicroPython"
---

# chumicro-kvstore

**A dict that keeps its values through a reset or a power cut.**

`KVStore` keeps a boot count, the last reading, a calibration value, or a login token on the board, and finds it again after a reset.  It works like a Python dict: change it as often as you like, then call `commit()` to save the change.  It picks the place to save for the board it runs on: `microcontroller.nvm` on CircuitPython, NVS (the ESP32's built-in settings storage) or a file in flash on MicroPython, and plain memory on a laptop.  NVM sits outside the CIRCUITPY drive.  On CircuitPython, saving works even while the drive is mounted on your laptop and your code cannot write files.

## Install

```bash
# CircuitPython (after `circup bundle-add ChuMicro/ChuMicro-Bundle`)
circup install chumicro_kvstore

# MicroPython
mpremote mip install github:ChuMicro/ChuMicro-Bundle/chumicro_kvstore

# CPython
pip install chumicro-kvstore
```

[Start here](https://chumicro.com/ChuMicro/guides/start-here/) takes a new board from flashing CircuitPython or MicroPython to running your own blink.  [Installing libraries](https://chumicro.com/ChuMicro/guides/install/) covers registering the bundle, the pre-compiled `.mpy` packages, the experimental channel, and why package names use a hyphen on PyPI and an underscore on the board.

## Quick example

Count how many times the board has started.  Press reset and the count goes up by one:

```python
import time

from chumicro_kvstore import KVStore

store = KVStore(backend="auto")            # picks NVM, NVS, or flash for this board
store["boot_count"] = store.get("boot_count", 0) + 1
store.commit()                             # saved: survives a reset or power cut
print(f"Boot count: {store['boot_count']}")

while True:
    time.sleep(5)
    print(f"Boot {store['boot_count']}, still running")
```

## Documentation

- [User Guide](guide.md): where each board saves, when to call `commit()` versus `commit_if_changed()`, how much fits, what happens to damaged data, and platform notes
- [API Reference](api.md): `KVStore` and its methods, and the `KVStoreFull` / `KVStoreCorrupt` exceptions
- [Testing Helpers](testing.md): `FakeKVStore`, an in-memory store for your tests

---

<div class="chumicro-footer" markdown>

[← All ChuMicro Libraries](../../)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/kvstore) · \
[PyPI](https://pypi.org/project/chumicro-kvstore/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
