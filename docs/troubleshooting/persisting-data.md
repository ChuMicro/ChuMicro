# Persisting data

`chumicro-kvstore` keeps small values, such as a boot counter, a token, or a changed setting, across a reset or a power cut. A program can also write files of its own.

`chumicro-kvstore` picks where to save on its own. On CircuitPython it writes to `microcontroller.nvm`, a small block of storage outside the filesystem. On MicroPython it uses the ESP32's built-in key-value storage, NVS, or a file named `/_chu_kv.msgpack` on boards without NVS, such as the Pi Pico W. A deploy keeps that file, as [Deploys and file persistence](deploys-and-file-persistence.md#a-deploy-deleted-files-put-on-the-board-by-hand) lists.

## `RuntimeError: Cannot remount path when visible via USB.`

A boot counter or saved setting needs no file writes: `chumicro-kvstore` writes to `microcontroller.nvm`, outside the filesystem.

To write files from your program, hand write access to it in `boot.py`, which runs before USB connects. Put the switch on a button so the board can still take deploys. Adafruit's [CircuitPython Storage guide](https://learn.adafruit.com/circuitpython-essentials/circuitpython-storage) shows a `boot.py` that gives your program write access only when a button is held at power-up. Put that `boot.py` in your project folder and the deploy sends it.

While your program holds write access, `CIRCUITPY` shows up read-only on your laptop and deploys fail. To get the drive back, reset without holding the button. Or open the board's REPL with `python3 run.py repl`, delete `boot.py`, and press RESET:

```python
import os
os.remove("/boot.py")
```

The program tried to write a file while the laptop held the `CIRCUITPY` drive. CircuitPython lets one side at a time write to its filesystem: by default the laptop, through the `CIRCUITPY` drive, or else your program. A deploy writes through the `CIRCUITPY` drive, so it needs the laptop side.

MicroPython has no `CIRCUITPY` drive, so programs there write files freely.

## `commit()` raises `KVStoreFull`

`store.capacity` gives the bytes left for your data.

Store less: drop a key you no longer need and commit again. A failed `commit()` leaves your values in memory untouched, so a retry loses nothing. For more room, save the larger data to a file instead.

On CircuitPython the store lives in `microcontroller.nvm`, and the chip fixes its size: 4 KB on an RP2040, 8 KB on an ESP32. The store keeps 10 bytes of that for its own bookkeeping.

## Saved data comes back empty after a power cut

Check `store.is_corrupt` right after creating the store, and react to it, for example by restoring defaults and committing them. For an exception instead, call `store.reload()`, which raises `KVStoreCorrupt`. Writing less often shrinks the window: `store.commit_if_changed()` skips the write when nothing changed.

```python
from chumicro_kvstore import KVStore

store = KVStore()
if store.is_corrupt:
    print("saved data was damaged; counting from zero again")
store["boots"] = store.get("boots", 0) + 1
store.commit_if_changed()
```

A power drop during a write can cut the saved copy short. On the next start the store notices, starts empty instead of raising, and sets `store.is_corrupt` to `True`. On an ESP32 the whole saved block can be lost this way, because the chip erases it before rewriting.

## A stored number comes back different, or `commit()` refuses it

Store times as seconds counted from a recent date you choose, or as a string, and keep large counters below a billion.

The store saves values in msgpack, a compact binary format, and keeps numbers small to suit the boards:

- **Decimals** keep about seven significant digits, so `1751414400.5` comes back as `1751414400.0`.
- **Whole numbers** must fit in 32 bits on MicroPython, and in 31 bits, up to 1,073,741,823, on CircuitPython. A Unix timestamp in milliseconds is too large everywhere: MicroPython raises `OverflowError`. A Unix timestamp in seconds already passes the CircuitPython limit, where `commit()` raises `ValueError: no default packer`.

## `ValueError: float64 (0xcb) not in chumicro msgpack subset`

Pack msgpack on the laptop with single precision:

```python
msgpack.packb(obj, use_single_float=True)
```

The `msgpack` package from PyPI saves decimals at full 64-bit precision by default. The boards read only the 32-bit form. The deploy already packs its config file in single precision, so this error comes only from msgpack you pack yourself.
