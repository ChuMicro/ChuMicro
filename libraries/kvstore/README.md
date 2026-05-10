# chumicro-kvstore

<img src="https://raw.githubusercontent.com/ChuMicro/ChuMicro/main/support/docs/chumicro_tip.png"
align="left" width="64" style="margin-right: 16px; margin-bottom: 8px;">

Tiny mutable key-value store for persisted runtime state — counters, timestamps, tokens, retry budgets — across CircuitPython, MicroPython, and CPython.  **Not** a config system; for declarative config, use `chumicro-config`.

<br clear="left">

> Part of the [ChuMicro](https://github.com/ChuMicro/ChuMicro) family — small, focused Python libraries for microcontrollers and laptops. [Browse all libraries.](https://github.com/ChuMicro/ChuMicro/tree/main/libraries)

## Install

```bash
# CircuitPython (after `circup bundle-add ChuMicro/ChuMicro-Bundle`)
circup install chumicro-kvstore

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
| `KVStoreFull` / `KVStoreCorrupt` / `KVStoreReadOnly` | Targeted exceptions |
| `chumicro_kvstore.testing.FakeKVStore` | Drop-in for downstream tests with capacity + corruption hooks |

## Platform support

Works on CPython, MicroPython, and CircuitPython.

## Examples

| Example | What it shows |
|---|---|
| [`boot_counter.py`](examples/boot_counter.py) | Boot counter persisted across reboots; auto-detect picks the right backend per runtime |

## Developing this library

Host-side tests live in `tests/`; real-board functional tests belong in `functional_tests/`.

```bash
pip install -e .[test]
pytest tests/
pytest functional_tests/   # needs a registered board in devices.yml
```

Before running functional tests, register a board with `chumicro-workspace add-device <id> --address <port>`.

## Docs

📖 **[Stable docs](https://chumicro.github.io/ChuMicro/kvstore/stable/)** · **[Experimental docs](https://chumicro.github.io/ChuMicro/kvstore/experimental/)**

## Find this library

- **PyPI:** [chumicro-kvstore](https://pypi.org/project/chumicro-kvstore/)
- **Bundle:** [ChuMicro-Bundle](https://github.com/ChuMicro/ChuMicro-Bundle/tree/main/chumicro_kvstore) (CircuitPython & MicroPython)
- **Experimental bundle:** [ChuMicro-Bundle-Experimental](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental/tree/main/chumicro_kvstore)
- **Source:** [libraries/kvstore](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/kvstore)
