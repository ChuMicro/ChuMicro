"""Keep a small dict of values on a CircuitPython or MicroPython board through a reset or a power cut.

On CPython the same code runs with the values held in memory only.
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
