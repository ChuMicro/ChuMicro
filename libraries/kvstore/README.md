# chumicro-kvstore

<img src="https://raw.githubusercontent.com/ChuMicro/ChuMicro/main/support/docs/chumicro_tip.png"
align="left" width="64" style="margin-right: 16px; margin-bottom: 8px;">

**A persistent dict for counters, timestamps, and tokens that need to survive a reboot.**

A dict-shaped store with `commit()` semantics.  Auto-detects the right backend per runtime (NVM on CircuitPython, NVS on ESP32 MicroPython, LittleFS elsewhere, in-memory for tests), bounds writes with `commit_if_changed()` so unchanged state doesn't wear the flash, and surfaces capacity and corruption honestly.  Not a config system — for declarative settings see [`chumicro-config`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/config).

<br clear="left">

> Part of the [ChuMicro](https://github.com/ChuMicro/ChuMicro) family — small, focused Python libraries for microcontrollers and laptops. [Browse all libraries.](https://github.com/ChuMicro/ChuMicro/tree/main/libraries)

## Install

```bash
# CircuitPython (after `circup bundle-add ChuMicro/ChuMicro-Bundle`)
circup install chumicro_kvstore

# MicroPython
mpremote mip install github:ChuMicro/ChuMicro-Bundle/chumicro_kvstore

# CPython
pip install chumicro-kvstore
```

For bundle setup, pre-compiled `.mpy` bundles, the experimental channel, and details on PyPI naming, see the [chumicro INSTALL guide](https://github.com/ChuMicro/ChuMicro/blob/main/INSTALL.md).

## Quick example

Boot counter that survives reboot:

```python
from chumicro_kvstore import KVStore

store = KVStore(backend="auto")
store["boot_count"] = store.get("boot_count", 0) + 1
store.commit_if_changed()              # no flash write if value unchanged
print(store["boot_count"])             # → 1, 2, 3, … across power cycles
```

## What's included

| Symbol | What it does |
|---|---|
| `KVStore(backend="auto")` | Mapping-shaped store; auto-detect picks NVM (CP), NVS (MP-ESP32), LittleFS (MP non-NVS), or memory (CPython) |
| `store[key]` / `store[key] = v` / `del store[key]` | Standard dict semantics |
| `store.commit()` | Encode + persist current state |
| `store.commit_if_changed()` | Skip write when payload is unchanged (wear defense) |
| `store.reload()` | Discard in-memory state, reread from backend |
| `store.capacity` / `bytes_used` / `is_corrupt` / `backend_name` | Honest substrate introspection |
| `KVStoreFull` / `KVStoreCorrupt` | Targeted exceptions (catch `KVStoreError` for both) |
| `chumicro_kvstore.testing.FakeKVStore` | Drop-in for downstream tests with capacity + corruption hooks |

## Where this fits

Leaf — no upstream ChuMicro deps.  Used directly in app code; no other ChuMicro library depends on it.

## Platform support

Works on CPython, MicroPython, and CircuitPython.

## Examples

| Example | What it shows |
|---|---|
| [`boot_counter.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/kvstore/examples/boot_counter.py) | Boot counter persisted across reboots; auto-detect picks the right backend per runtime |

## Contributing

Working on `chumicro-kvstore` itself?  Clone the [mono-repo](https://github.com/ChuMicro/ChuMicro) if you haven't already — the rest of the workflow assumes you're inside that workspace.

```bash
pip install -e .[test]
pytest tests/                  # host-side tests
pytest functional_tests/       # on-device tests (needs a board registered in devices.yml)
```

Register a board before running functional tests: `chumicro-workspace add-device <id> --address <port>`.

## Docs

📖 **[Stable docs](https://chumicro.github.io/ChuMicro/kvstore/stable/)** · **[Experimental docs](https://chumicro.github.io/ChuMicro/kvstore/experimental/)**

## Find this library

- **PyPI:** [chumicro-kvstore](https://pypi.org/project/chumicro-kvstore/)
- **Bundle:** [ChuMicro-Bundle](https://github.com/ChuMicro/ChuMicro-Bundle/tree/main/chumicro_kvstore) (CircuitPython & MicroPython)
- **Experimental bundle:** [ChuMicro-Bundle-Experimental](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental/tree/main/chumicro_kvstore)
- **Source:** [libraries/kvstore](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/kvstore)

## License

[MIT](https://github.com/ChuMicro/ChuMicro/blob/main/LICENSE)
