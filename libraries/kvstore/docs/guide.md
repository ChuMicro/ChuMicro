# User Guide

## Overview

`chumicro-kvstore` keeps a small dict of values on the board through a reset or a power cut: a boot counter, the last reading, calibration values, a refreshed access token.  `KVStore` behaves like a dict, with `store[key] = value`, `del store[key]`, `"key" in store`, and `for key in store`.  A change stays in memory until `commit()` or `commit_if_changed()` packs the dict into msgpack bytes and saves them.  `reload()` throws away unsaved changes and reads the saved copy again.

On CircuitPython the store saves into `microcontroller.nvm`, a small block of flash kept apart from the CIRCUITPY drive.  CircuitPython code can write NVM while a computer has CIRCUITPY mounted, so the store saves with the board plugged in to USB.

## Getting started

Count how many times the board has started, then keep running.  Press reset and the count goes up by one:

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

`KVStore(backend="auto")` reads the saved values once, when the store is created.  Every later read comes from memory.  Assigning a value changes memory only.  `commit()` saves it.  On a laptop, `auto` picks plain memory, so the count starts at 1 on every run.

## Where each board saves

| Backend | Where the bytes live | Room by default | Picked by `auto` on |
|---|---|---|---|
| `nvm` | CircuitPython's `microcontroller.nvm`, with a checksum to catch a half-written save | The chip's NVM size minus 10 bytes | CircuitPython, every board |
| `nvs` | MicroPython's `esp32.NVS`, the ESP32's built-in settings storage, as one entry named `payload` in the `chu_kv` namespace | 512 bytes | MicroPython on ESP32-family boards |
| `littlefs` | The file `/_chu_kv.msgpack` in MicroPython's flash filesystem, written to a temporary file first and then renamed into place | 16 KB | MicroPython on other boards, such as Pi Pico W |
| `memory` | Plain memory, gone when the program ends | No limit | CPython on a laptop |

Pass a backend's name to use it on any runtime, such as `littlefs` on an ESP32 or `memory` in a test:

```python
store = KVStore(backend="littlefs")
store = KVStore(backend="memory")
```

`KVStore(backend=...)` also takes a backend object of your own: any object with a `name`, a `capacity` in bytes (0 for no limit), a `load()` that returns the saved bytes, and a `save(payload)` that stores them.  `MpNvsBackend(capacity=N)` from `chumicro_kvstore._backends.mp_nvs` and `MpLittlefsBackend(capacity=N)` from `chumicro_kvstore._backends.mp_littlefs` raise the default room.  The default NVS partition holds 24 KB.  A `littlefs` store can grow to the free space on the filesystem.

Tests create `FakeKVStore()` from `chumicro_kvstore.testing` in place of the whole `KVStore`, which it subclasses ([Testing Helpers](testing.md)).

## Saving: `commit()` and `commit_if_changed()`

Every save writes flash, and flash wears out after a limited number of writes.  Save when a value changes, never on a fast timer.

| Method | What it does | When to use |
|---|---|---|
| `commit()` | Packs and saves the dict on every call. | Right after a change that matters, such as a new boot count. |
| `commit_if_changed()` | Saves only when a value changed since the last save, and returns `True` when it wrote. | In a loop or on a timer, where most calls have nothing new to save. |
| `reload()` | Throws away unsaved changes and reads the saved copy again.  Raises `KVStoreCorrupt` on damaged data. | To undo changes made since the last save. |

A [runner](https://chumicro.com/ChuMicro/runner/stable/guide/#timed-jobs) job that calls `commit_if_changed()` once a second writes flash only after a change.  The runner passes the time to every job, so the job takes a `now_ms` argument and ignores it:

```python
def save_changes(now_ms):
    store.commit_if_changed()

runner.add_periodic(save_changes, period_ms=1000)
```

## How much fits

`store.capacity` is the number of bytes the store can save.  `store.bytes_used` is the number the current values take once packed.  A boot counter, a timestamp, and a few flags take a few dozen bytes.

CircuitPython NVM is the smallest backend.  Its size depends on the chip: 256 bytes on SAMD21 boards, 4 KB on RP2040 boards such as Pi Pico W, and 8 KB on SAMD51 and ESP32 boards.  `len(microcontroller.nvm)` gives the size on the board at hand.  The store keeps 10 of those bytes for its header.

When the values do not fit, `commit()` raises `KVStoreFull` and saves nothing.  The values in memory stay as they were, so the program can drop a key and commit again:

```python
from chumicro_kvstore import KVStoreFull

try:
    store.commit()
except KVStoreFull:
    del store["debug_log"]
    store.commit()
```

## Damaged data

A reset or power cut in the middle of a save can leave damaged data behind.  The `nvm` backend stores a checksum with every save and checks it on load.  The `nvs` and `littlefs` backends replace the old save in one step, so a load finds either the old save or the new one.  A blank NVM, as it comes from the factory, loads as an empty store.

A new `KVStore` that finds damaged data starts empty and sets `is_corrupt`.  The program keeps running:

```python
store = KVStore(backend="auto")
if store.is_corrupt:
    print("Saved data was damaged.  Starting from empty.")
```

`reload()` raises `KVStoreCorrupt` on damaged data, for code that stops and reports it.  `KVStoreFull` and `KVStoreCorrupt` both subclass `KVStoreError`, so one `except KVStoreError:` catches either.  Creating a store on a board with no NVM at all raises, because the store has nowhere to save.

## Iteration and update

The usual dict methods work:

```python
for key, value in store.items():
    print(key, value)

store.update({"counter_a": 42, "counter_b": 99})
store.commit_if_changed()
```

`clear()`, `pop(key, default)`, `keys()`, `values()`, and `items()` behave as they do on a dict.  Each one changes memory only.  `commit()` or `commit_if_changed()` saves the result.

## Value types

The store packs values with [`chumicro-msgpack`](https://chumicro.com/ChuMicro/msgpack/stable/guide/#supported-types), so a value can be any type in its Supported types table.  That table gives the integer range on each runtime and the precision of a saved `float`.

## Platform notes

[Where each board saves](#where-each-board-saves) lists the backend `auto` picks on each runtime.  The store imports a backend's code only when it picks that backend, so a board loads only the one it uses.

## Examples

| Example | What it shows |
|---|---|
| [`examples/boot_counter.py`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/kvstore/examples/boot_counter.py) | Counts board starts with `commit()`, prints `backend_name`, `bytes_used`, and `capacity`, then prints the count every five seconds.  Runs on every runtime.  On a board the count survives a reset, and on CPython it starts at 1 on every run. |

---

<div class="chumicro-footer" markdown>

[← Home](index.md)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/kvstore) · \
[PyPI](https://pypi.org/project/chumicro-kvstore/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
