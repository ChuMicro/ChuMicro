# chumicro-kvstore

<img src="https://raw.githubusercontent.com/ChuMicro/ChuMicro/main/support/docs/chumicro_tip.png"
align="left" width="64" style="margin-right: 16px; margin-bottom: 8px;">

**A dict that keeps its values through a reset or a power cut.**

Keep a boot count, the last reading, a calibration value, or a login token on the board and find it again after a reset.  `KVStore` works like a Python dict: change it as often as you like, then call `commit()` when you want the change saved.  It picks the right place to save for the board it runs on: `microcontroller.nvm` on CircuitPython, NVS (the ESP32's built-in settings storage) or a file in flash on MicroPython, and plain memory on a laptop.  NVM sits outside the CIRCUITPY drive, so on CircuitPython saving works even while the drive is mounted on your computer and your code cannot write files.

<br clear="left">

> Part of the [ChuMicro](https://github.com/ChuMicro/ChuMicro) family: small, focused Python libraries for microcontrollers and laptops. [Browse all libraries.](https://github.com/ChuMicro/ChuMicro/tree/main/libraries)

## Install

```bash
# CircuitPython (after `circup bundle-add ChuMicro/ChuMicro-Bundle`)
circup install chumicro_kvstore

# MicroPython
mpremote mip install github:ChuMicro/ChuMicro-Bundle/chumicro_kvstore

# CPython
pip install chumicro-kvstore
```

For bundle setup, pre-compiled `.mpy` bundles, the experimental channel, and details on PyPI naming, see the [ChuMicro install guide](https://chumicro.com/ChuMicro/guides/install/).

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

Saving writes to flash, and flash wears out after many writes.  In a loop that might save often, call `store.commit_if_changed()` instead: it writes only when a value actually changed.

## What's included

| Symbol | What it does |
|---|---|
| `KVStore(backend="auto")` | Open the store; `"auto"` picks NVM (CircuitPython), NVS (MicroPython on ESP32), a flash file (other MicroPython boards), or memory (CPython) |
| `store[key]`, `store[key] = value`, `del store[key]`, `store.get(key, default)` | Read and change values the way you would in a dict |
| `store.commit()` | Save every value now |
| `store.commit_if_changed()` | Save only when something changed since the last save; a call with nothing new to save costs no flash write |
| `store.reload()` | Throw away unsaved changes and read the saved values again |
| `store.capacity`, `store.bytes_used` | How many bytes the store can hold, and how many the current values take |
| `store.is_corrupt`, `store.backend_name` | Whether the saved data was damaged at startup, and where the store saves |
| `KVStoreFull`, `KVStoreCorrupt` | Raised when a save does not fit, or `reload()` finds damaged data; catch `KVStoreError` for both |
| `chumicro_kvstore.testing.FakeKVStore` | An in-memory store for your own tests, with switches to make it full or corrupt |

## Where this fits

Depends on [`chumicro-msgpack`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/msgpack), which turns the dict into bytes for saving; `circup` and `mip` install it for you.  No other ChuMicro library depends on kvstore: use it directly in your own code.

## Platform support

Works on CPython, MicroPython, and CircuitPython.

## Examples

| Example | What it shows |
|---|---|
| [`boot_counter.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/kvstore/examples/boot_counter.py) | Counts board starts and keeps the count through a reset, then prints it every five seconds |

## Contributing

Issues, bug reports, and pull requests are welcome, and so is "I ran it on this board and here's what happened", some of the most useful feedback a hardware project can get.  Development happens in the [ChuMicro repository](https://github.com/ChuMicro/ChuMicro), whose contributing guide covers setup and the test workflow.

## Docs

📖 **[Stable docs](https://chumicro.com/ChuMicro/kvstore/stable/)** · **[Experimental docs](https://chumicro.com/ChuMicro/kvstore/experimental/)**

## Find this library

- **PyPI:** [chumicro-kvstore](https://pypi.org/project/chumicro-kvstore/)
- **Bundle:** [ChuMicro-Bundle](https://github.com/ChuMicro/ChuMicro-Bundle/tree/main/chumicro_kvstore) (CircuitPython & MicroPython)
- **Experimental bundle:** [ChuMicro-Bundle-Experimental](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental/tree/main/chumicro_kvstore)
- **Source:** [libraries/kvstore](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/kvstore)

## License

[MIT](https://github.com/ChuMicro/ChuMicro/blob/main/LICENSE)
