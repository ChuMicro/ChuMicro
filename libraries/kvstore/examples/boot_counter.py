"""Count how many times the board has started, and keep the count through a reset.

Each time the board starts, it reads the count it saved last time, adds one,
saves the new count, and prints it.  After that it prints the count and how
long it has been running every five seconds.  Press the reset button, or
unplug the board and plug it back in, and the count goes up by one.

``KVStore`` works like a dict that you save with ``commit()``.  On
CircuitPython it saves into ``microcontroller.nvm``, a small block of memory
that survives a reset.  On MicroPython it saves into the board's flash.  On a
laptop (CPython) it keeps the values in memory only, so the count starts at 1
every run there.

Setup:

1. Install the library.  On CircuitPython run
   ``circup install chumicro_kvstore``; on MicroPython run
   ``mpremote mip install github:ChuMicro/ChuMicro-Bundle/chumicro_kvstore``.
   Both also install ``chumicro_msgpack``, which ``KVStore`` uses to save.
2. No wiring needed.
3. Save this file as ``code.py`` (CircuitPython) or ``main.py``
   (MicroPython) on the board.

Example output on a Pi Pico W running CircuitPython, after two resets::

    Boot count: 3
    Saved in nvm: 13 of 4086 bytes used
    Press reset to make the count go up.
    Boot 3, running for 5 s
    Boot 3, running for 10 s
    Boot 3, running for 15 s

Runs on CPython, MicroPython, and CircuitPython.
"""

import time

from chumicro_kvstore import KVStore

# Open the store.  "auto" picks the storage that survives a reset on this board.
store = KVStore(backend="auto")

# Read the count saved last time (0 on the very first start), add one,
# and save it.  Nothing is saved until commit() runs.
store["boot_count"] = store.get("boot_count", 0) + 1
store.commit()

print(f"Boot count: {store['boot_count']}")
print(f"Saved in {store.backend_name}: {store.bytes_used} of {store.capacity} bytes used")
print("Press reset to make the count go up.")

# Keep running, and show the count every five seconds.
seconds_running = 0
while True:
    time.sleep(5)
    seconds_running += 5
    print(f"Boot {store['boot_count']}, running for {seconds_running} s")
