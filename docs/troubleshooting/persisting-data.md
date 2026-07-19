# Persisting data (KV store and config)

This page is for keeping data (boot counters, tokens, small config) across a reboot with `chumicro-kvstore` or the config library.  Most surprises here come from three facts about microcontroller storage: the running code and the USB host can't both write the filesystem at once, the non-volatile memory (NVM) slab is small and fixed per chip, and the on-device serializer keeps floats to 32 bits.

## `storage.remount("/", readonly=False)` raises `Cannot remount path when visible via USB.`

CircuitPython gives the USB host and the running Python code mutually exclusive write access to the filesystem, and the USB drive holds it by default.  So `code.py` cannot write to flash while your laptop has CIRCUITPY mounted.  (MicroPython has no such restriction.)

**Fix.** Hand write access to the running code by disabling the USB drive at boot.  In `boot.py`:

```python
import storage
storage.disable_usb_drive()   # CircuitPython 9 and later
```

or gate a remount on a GPIO pin in `boot.py`.  Note that the default kvstore `nvm` backend writes off-FAT and is unaffected; only filesystem-backed backends hit this window.  App config is deploy-time read-only by design.  (background: [Decision 0030](../../plans/decisions/0030-config-and-state.md))

## `commit()` raises `KVStoreFull`

On CircuitPython the KV store lives in `microcontroller.nvm`, a fixed per-chip byte slab: 256 B on a SAMD21, 4 KB on an RP2040, 8 KB on ESP32 and SAMD51.  On a SAMD21 that leaves 256 B minus 10 B of CRC framing, which fills fast.

**Fix.** Respect `store.capacity`.  Drop a key and retry (the in-memory dict is left unchanged when the commit raises), or move larger state to a LittleFS-backed or NVS-backed board.

## Persisted state reads back empty after a bad shutdown

On a bad-magic or CRC mismatch, or a blank slab left by `erase_filesystem()`, construction does not raise.  It resets to empty and reports the problem through `is_corrupt`.  A power cut mid-write can corrupt the whole ESP32 NVM blob, because erase-then-rewrite is not byte-atomic.

**Fix.** Check `store.is_corrupt` right after construction (or use `reload()`, which raises `KVStoreCorrupt` instead of resetting).  Use `commit_if_changed()` to cut flash wear.

## A stored float like `1751414400.5` reads back as `1751414400.0`

Values persist through msgpack (a compact binary serialization format) as 32-bit float32, which cannot hold that many significant digits.

**Fix.** Store timestamps and durations as integer milliseconds or seconds, not floats.

## `ValueError("float64 (0xcb) not in chumicro msgpack subset; encode with msgpack.packb(obj, use_single_float=True)")`

The PyPI `msgpack` package encodes floats as float64 by default, which is outside the subset the device decoder accepts.

**Fix.** Encode host-side with single floats:

```python
msgpack.packb(obj, use_single_float=True)
```

The workspace deploy tool already does this for `runtime_config.msgpack`, so you only hit this when packing msgpack yourself.
