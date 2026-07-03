"""KVStore boot counter: a value that survives reboot.

Shows the classic boot-counter pattern: read a value at boot, increment
it, persist it.  On a real device this number goes up by one every
power cycle.

Runs on CPython (with the in-process memory backend), MicroPython, and
CircuitPython (with the runtime-appropriate persistent backend).

Example output::

    Boot count: 1
    Bytes used: 13 / 9223372036854775807
    Backend: memory
"""

from chumicro_kvstore import KVStore

store = KVStore(backend="auto")
store["boot_count"] = store.get("boot_count", 0) + 1
store.commit_if_changed()

print(f"Boot count: {store['boot_count']}")
print(f"Bytes used: {store.bytes_used} / {store.capacity}")
print(f"Backend: {store.backend_name}")
