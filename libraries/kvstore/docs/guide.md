# User Guide

## Overview

`chumicro-kvstore` keeps a small dict of values on the board where they survive a reset or a power cut: boot counters, the last reading, calibration values, refreshed access tokens.  `KVStore` behaves like a dict (`store[key] = value`, `del store[key]`, `"key" in store`, `for key in store`).  Changes stay in memory until you call `commit()` or `commit_if_changed()`, which pack the dict into msgpack bytes and save them.  `reload()` throws away unsaved changes and reads the saved copy again.

On CircuitPython the store saves into `microcontroller.nvm`, a few kilobytes of memory kept apart from the CIRCUITPY drive.  Your code cannot write files while CIRCUITPY is mounted on your computer, but it can always write NVM, so saving works with the board plugged in.

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

`KVStore(backend="auto")` reads the saved values once, when you create it.  After that every read comes from memory and never touches flash.  Assigning a value changes memory only; `commit()` saves.  On a laptop the `auto` choice is plain memory, so the count starts at 1 on every run there.

## Where each board saves

| Backend | Where the bytes live | Picked by `auto` on |
|---|---|---|
| `nvm` | CircuitPython's `microcontroller.nvm`, with a checksum to catch a half-written save | CircuitPython, every board |
| `nvs` | MicroPython's `esp32.NVS`, the ESP32's built-in settings storage (one entry named `payload` in the `chu_kv` namespace) | MicroPython on ESP32-family boards |
| `littlefs` | The file `/_chu_kv.msgpack` in MicroPython's flash filesystem, written to a temporary file first and then renamed into place | MicroPython on other boards, such as Pi Pico W |
| `memory` | Plain memory, gone when the program ends | CPython on a laptop, and `FakeKVStore` in tests |

To use one backend whatever the runtime (in tests, or to use `littlefs` on an ESP32 whose NVS gives trouble), pass its name:

```python
store = KVStore(backend="littlefs")
store = KVStore(backend="memory")
```

You can also pass your own backend object: anything with a `name`, a `capacity` in bytes (0 for no limit), a `load()` that returns the saved bytes, and a `save(payload)` that stores them.  In tests, create a `FakeKVStore()` in place of the whole store; it is a `KVStore`, not a backend (see [Testing Helpers](testing.md)).

## Saving: `commit()` and `commit_if_changed()`

Every save writes flash, and flash wears out after a limited number of writes, so save when a value changes rather than on a fast timer.

| Method | What it does | When to use |
|---|---|---|
| `commit()` | Packs and saves the dict every time. | Right after a change you know matters, such as a new boot count. |
| `commit_if_changed()` | Saves only when a value changed since the last save, and returns `True` when it wrote. | In a loop or on a timer, where most calls have nothing new to save. |
| `reload()` | Throws away unsaved changes and reads the saved copy again; raises `KVStoreCorrupt` on damaged data. | When you suspect something else changed the saved data. |

Saving once a second with a runner costs a flash write only when a value changed.  The runner passes the current time to each handler, so wrap the call:

```python
def save_changes(now_ms):
    store.commit_if_changed()

runner.add_periodic(save_changes, period_ms=1000)
```

## How much fits

`store.capacity` is how many bytes the store can save, and `store.bytes_used` is how many the current values take once packed.  A boot counter, a timestamp, and a few flags take a few dozen bytes.

CircuitPython NVM is the smallest backend, and its size depends on the chip: 256 bytes on SAMD21 boards, 4 KB on RP2040 boards such as Pi Pico W, and 8 KB on SAMD51 and ESP32 boards.  The store keeps 10 of those bytes for its header, and `len(microcontroller.nvm)` tells you the size on your board.  On MicroPython, `littlefs` holds 16 KB by default and `nvs` holds 512 bytes.

When the values do not fit, `commit()` raises `KVStoreFull` and saves nothing.  The values in memory stay as they were, so you can drop a key and try again:

```python
from chumicro_kvstore import KVStoreFull

try:
    store.commit()
except KVStoreFull:
    del store["debug_log"]
    store.commit()
```

## Damaged data

A save that a reset or power cut interrupts halfway can leave damaged data behind.  The `nvm` backend stores a checksum with every save and checks it on load.  The `nvs` and `littlefs` backends replace the old save in one step, so a reader sees either the old save or the new one.  A blank NVM, as it comes from the factory, reads as an empty store.

Creating a `KVStore` never raises on damaged data.  The store starts empty instead and sets `is_corrupt`, so your program keeps running:

```python
store = KVStore(backend="auto")
if store.is_corrupt:
    print("Saved data was damaged; starting from empty.")
```

`reload()` raises `KVStoreCorrupt` on damaged data instead, for code that wants to stop and report it.  `KVStoreFull` and `KVStoreCorrupt` both subclass `KVStoreError`, so one `except KVStoreError:` catches either.  A board that has no NVM at all still raises when you create the store, because there is nowhere to save.

## Iteration and update

The usual dict methods work:

```python
for key, value in store.items():
    print(key, value)

store.update({"counter_a": 42, "counter_b": 99})
store.commit_if_changed()
```

`clear()`, `pop(key, default)`, `keys()`, `values()`, and `items()` behave as they do on a dict.  None of them save: call `commit()` or `commit_if_changed()` when you want a change kept.

## Value types

The store saves values with msgpack, so a value can be `None`, a `bool`, an `int` from -2,147,483,648 to 4,294,967,295, a `str`, `bytes`, or a `list` or `dict` of those, nested up to 8 levels deep.  A `float` saves as a 32-bit float, which keeps about 7 significant digits: a `time.time()` timestamp such as `1751414400.5` reads back as `1751414400.0`.  Store timestamps and durations as whole milliseconds or seconds instead.

## Platform notes

| Runtime | Backend chosen by `auto` | Capacity (typical) |
|---|---|---|
| CircuitPython | `nvm` (with a checksum) | 256 B to 8 KB depending on the chip |
| MicroPython on ESP32-family | `nvs` (one entry in the `chu_kv` namespace) | 512 B default; raise it with `KVStore(backend=MpNvsBackend(capacity=N))` (the default NVS partition is 24 KB) |
| MicroPython on Pi Pico W (rp2) | `littlefs` (the file `/_chu_kv.msgpack`) | 16 KB default; raise it with `KVStore(backend=MpLittlefsBackend(capacity=N))`, up to the free space on the filesystem |
| CPython | `memory` | no limit |

Each backend's code is imported only when the store picks it, so a board loads only the one it uses.

## Examples

| Example | What it shows |
|---|---|
| [`examples/boot_counter.py`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/kvstore/examples/boot_counter.py) | Counts board starts with `commit()`, prints `backend_name`, `bytes_used`, and `capacity`, then prints the count every five seconds.  Runs on every runtime; on a board the count survives a reset, on CPython it starts at 1 every run. |

---

<div class="chumicro-footer" markdown>

[← Home](index.md)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/kvstore) · \
[PyPI](https://pypi.org/project/chumicro-kvstore/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
