"""Persisted runtime state for CircuitPython, MicroPython, and CPython.

A tiny mutable key-value store for state that must survive reboot —
counters, timestamps, tokens, retry budgets.  Not a config system,
not a database.

Public API::

    from chumicro_kvstore import KVStore, KVStoreFull, KVStoreCorrupt
    # KVStoreError is the shared base — catch it for any kvstore failure.

    store = KVStore(backend="auto")
    store["boot_count"] = store.get("boot_count", 0) + 1
    store.commit()

Per-runtime backends ship with the library:

* ``"nvm"`` — CP ``microcontroller.nvm`` byte slab + CRC framing.
* ``"nvs"`` — MP ESP32 ``esp32.NVS`` namespaced K-V.
* ``"littlefs"`` — MP non-NVS boards; single ``/_chu_kv.msgpack`` file.
* ``"memory"`` — CPython default + ``FakeKVStore`` substrate.
"""

from chumicro_kvstore.core import (
    KVStore,
    KVStoreCorrupt,
    KVStoreError,
    KVStoreFull,
)

__all__ = [
    "KVStore",
    "KVStoreCorrupt",
    "KVStoreError",
    "KVStoreFull",
]
