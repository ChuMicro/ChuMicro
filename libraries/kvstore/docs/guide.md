# User Guide

## Overview

`chumicro-kvstore` is a tiny mutable key-value store for runtime state that needs to survive a reboot — boot counters, last-seen timestamps, retry budgets, refreshed access tokens.  It exposes a familiar `dict`-shaped API (`store[key] = value`, `del store[key]`, `"key" in store`, iteration) plus three explicit lifecycle methods: `commit`, `commit_if_changed`, `reload`.

It is **not** a config system.  Config is read-only at deploy time, structured by section, and lives at `/runtime_config.msgpack` ([`chumicro-config`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/config)).  KVStore is read-write at runtime, flat, and lives in the right per-runtime persistent backend (CP NVM with CRC framing, MP NVS, MP LittleFS, or in-memory).

## Getting started

The "boot counter that survives reboot" pattern in five lines:

```python
from chumicro_kvstore import KVStore
from chumicro_timing import ticks_ms

store = KVStore(backend="auto")
store["boot_count"] = store.get("boot_count", 0) + 1
store["last_seen_ms"] = ticks_ms()
store.commit_if_changed()
```

`backend="auto"` picks the right backend per runtime (see below).  Reads are pure-memory after the constructor's auto-load — no I/O on the hot path.  Writes update the in-memory dict immediately; persistence happens on the next `commit*` call.

## Backends and `auto` selection

| Backend | Where the bytes live | Selected on |
|---|---|---|
| `nvm` | CircuitPython `microcontroller.nvm` byte slab with CRC32 framing | CircuitPython on every supported board |
| `nvs` | MicroPython `esp32.NVS` namespaced K-V (single `payload` blob in the `chu_kv` namespace) | MicroPython on ESP32-family boards (auto-detected via `import esp32`) |
| `littlefs` | MicroPython LittleFS file at `/_chu_kv.msgpack`, atomic via tmp-file + rename | MicroPython on non-NVS boards (Pi Pico W, etc.) |
| `memory` | In-process `bytes` — does **not** survive process exit | CPython default, plus `FakeKVStore` for tests |

The auto-select ladder is one short function:

```python
import sys

def _select_backend():
    if sys.implementation.name == "circuitpython":
        return CpNvmBackend()
    if sys.implementation.name == "micropython":
        try:
            import esp32          # ESP32-family probe
            return MpNvsBackend()
        except ImportError:
            return MpLittlefsBackend()
    return MemoryBackend()        # CPython
```

If you want a specific backend regardless of runtime — for tests, or to force `littlefs` on an ESP32 with NVS issues — pass it by name:

```python
store = KVStore(backend="littlefs")
store = KVStore(backend="memory")
```

Or pass a backend instance directly (typically a `FakeKVStore` in tests; see [Testing Helpers](testing.md)).

## Commit semantics

Three lifecycle methods, distinct intents:

| Method | What it does | When to use |
|---|---|---|
| `commit()` | Always re-encode + write. | After a logical change you know is significant. |
| `commit_if_changed()` | Re-encode; skip the write if bytes match the last persisted payload. | Hot loops or once-per-tick "save current state" calls — first-line defense against flash wear on the raw NVM backend. |
| `reload()` | Discard in-memory state, reread from backend, raise on corruption. | Recovery — explicit re-read after suspicion of external write or corruption. |

```python
# Safe to call every tick — only writes when something actually changed.
runner.add_periodic(store.commit_if_changed, period_ms=1000)
```

## Sizing and full-store handling

Each backend exposes a `capacity` (bytes-of-encoded-payload).  `KVStore.bytes_used` reports the current encoded size; `KVStore.capacity` reports the backend's limit.

CP NVM is the smallest — typically 256 bytes on SAMD21 boards, ~4 KB on RP2040 (the reference Pi Pico W), and 8 KB on SAMD51 / ESP32 boards (it's per-chip; check your board's `microcontroller.nvm`).  After CRC framing overhead (10 bytes), you have your usable budget.  `commit()` raises `KVStoreFull` if the encoded payload won't fit; the in-memory dict is unchanged so you can drop a key and retry:

```python
try:
    store.commit()
except KVStoreFull:
    del store["debug_log"]
    store.commit()
```

A few keys with short string / int values (boot counters, timestamps, simple flags) easily fit in 256 B.  Larger state — captured sensor traces, queued telemetry — wants the LittleFS or NVS backend, which give you tens of KB.

## Corruption handling

The CP NVM backend is the only one with explicit framing (magic `b"CKVS"` + length + CRC32 + payload).  A blank slab from `storage.erase_filesystem()` reads as empty.  A bad-magic or CRC-mismatch reads as corrupt.

Construction never raises on corruption — the store resets to empty and reports the event via `is_corrupt`:

```python
store = KVStore(backend="auto")
if store.is_corrupt:
    log.warning("kvstore was corrupt; starting fresh")
    # store["boot_count"] etc. starts at 0
```

`reload()` is the explicit form that *does* raise (`KVStoreCorrupt`) — use it when you want to surface the failure rather than silently reset.

NVS is atomic-on-commit at the backend level (no CRC needed).  LittleFS uses tmp-file + rename for atomicity (no CRC needed).  Memory backend can't corrupt.

## Iteration and update

Standard mapping API works:

```python
for key, value in store.items():
    print(key, value)

store.update({"counter_a": 42, "counter_b": 99})
store.commit_if_changed()
```

`clear()`, `pop(key, default)`, `keys()`, `values()`, `items()` follow `dict` semantics.  `commit` is **not** implied by mutating methods — you call it explicitly when you want the change persisted.

## Value types

Values are stored via msgpack in the chumicro subset: `None`, `bool`, `int` (32-bit), `str`, `bytes`, and nested `list` / `dict` up to 8 levels deep.  Floats encode as **32-bit** (`float32`), so a value like a `time.time()` timestamp loses precision through a commit / reload round-trip (e.g. `1751414400.5` reads back as `1751414400.0`).  Store timestamps and durations as integer milliseconds or seconds, not floats.

## Platform notes

| Runtime | Backend chosen by `auto` | Capacity (typical) |
|---|---|---|
| CircuitPython | `nvm` (with CRC framing) | 256 B – 8 KB depending on chip |
| MicroPython on ESP32-family | `nvs` (single blob in `chu_kv` namespace) | 512 B default; pass `capacity=N` for larger (~24 KB partition headroom) |
| MicroPython on Pi Pico W (rp2) | `littlefs` (atomic file at `/_chu_kv.msgpack`) | 16 KB default; pass `capacity=N` for larger (then filesystem-bounded) |
| CPython | `memory` (in-process bytes) | unbounded |

`MemoryBackend` is **lazy-imported** — device runtimes that resolve `auto` to `nvm` / `nvs` / `littlefs` never pay the ~700 B import cost.

### USB-MSC read-only window (CircuitPython)

While the host has CIRCUITPY mounted, the device can't `storage.remount(readonly=False)` to write to flash.  The default `nvm` backend on CircuitPython writes to NVM (not the FAT volume) so it's unaffected — the boot-counter pattern continues to persist across reboots even with the drive mounted.

## Examples

| Example | What it shows |
|---|---|
| [`examples/boot_counter.py`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/kvstore/examples/boot_counter.py) | Boot-counter pattern: `commit_if_changed`, `bytes_used`, `backend_name`.  Runs on every runtime; on CPython the count resets each invocation, on a real device it survives reboot. |

---

<div class="chumicro-footer" markdown>

[← Home](index.md)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/kvstore) · \
[PyPI](https://pypi.org/project/chumicro-kvstore/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
