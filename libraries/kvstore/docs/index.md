---
title: "chumicro-kvstore: storage that survives a reboot on CircuitPython and MicroPython"
---

# chumicro-kvstore

**A dict that keeps its values through a reset or a power cut.**

Counters, last readings, calibration values, and tokens that your program changes while it runs and still finds after the board restarts.  `KVStore` works like a Python dict: change it as often as you like, then call `commit()` when you want the change saved.  It saves to `microcontroller.nvm` on CircuitPython, which works even while the CIRCUITPY drive is mounted on your computer, and to NVS or a flash file on MicroPython.

## Install

```bash
# CircuitPython (after `circup bundle-add ChuMicro/ChuMicro-Bundle`)
circup install chumicro_kvstore

# MicroPython
mpremote mip install github:ChuMicro/ChuMicro-Bundle/chumicro_kvstore

# CPython
pip install chumicro-kvstore
```

No board running yet?  [Start here](https://chumicro.com/ChuMicro/guides/start-here/) goes from a new board to your own code running on it.  [Installing libraries](https://chumicro.com/ChuMicro/guides/install/) covers registering the bundle, the experimental channel, and the pre-compiled `.mpy` packages.

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

- [User Guide](guide.md): where each board saves, when to call `commit()` versus `commit_if_changed()`, how much fits, what happens to damaged data, platform notes
- [API Reference](api.md): `KVStore` methods, `commit_if_changed`, and the `KVStoreFull` / `KVStoreCorrupt` exceptions
- [Testing Helpers](testing.md): using `FakeKVStore` in your tests

---

<div class="chumicro-footer" markdown>

[← All ChuMicro Libraries](../../)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/kvstore) · \
[PyPI](https://pypi.org/project/chumicro-kvstore/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
