"""Persisted runtime state for CircuitPython, MicroPython, and CPython.

A small mutable key-value store for state that must survive reboot:
counters, timestamps, tokens, retry budgets. Not a config system, not a
database. A per-runtime backend is selected automatically.
"""

import gc

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

gc.collect()
