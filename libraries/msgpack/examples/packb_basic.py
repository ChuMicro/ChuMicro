"""Pack a sensor reading into bytes and unpack it again, once a second.

Every second the board builds a small dict holding a counter and a pretend
temperature, turns it into msgpack bytes with ``packb``, and prints how many
bytes that took and the bytes themselves in hex.  Then ``unpackb`` turns the
bytes back into the same dict.  The reading changes each time, so you can
watch the bytes change with it.  Once the counter passes 127 it needs one
more byte.

msgpack is a binary format that does the job JSON does in fewer bytes.  The
bytes from ``packb`` are what you would save to memory, write to a file, or
send over the network.

Setup:

1. Install the library.  On CircuitPython run
   ``circup install chumicro_msgpack``; on MicroPython run
   ``mpremote mip install github:ChuMicro/ChuMicro-Bundle/chumicro_msgpack``.
2. No wiring needed.
3. Save this file as ``code.py`` (CircuitPython) or ``main.py``
   (MicroPython) on the board.

Example output::

    20 bytes: 82a5636f756e7401a674656d705f63ca41a40000
    unpacked: {'count': 1, 'temp_c': 20.5}
    20 bytes: 82a5636f756e7402a674656d705f63ca41a80000
    unpacked: {'count': 2, 'temp_c': 21.0}

Runs on CPython, MicroPython, and CircuitPython.
"""

import time

from chumicro_msgpack import packb, unpackb

count = 0

while True:
    count += 1
    # A pretend temperature that climbs from 20.0 to 24.5 and starts over.
    reading = {"count": count, "temp_c": 20.0 + (count % 10) / 2}

    # packb turns the dict into bytes.
    data = packb(reading)
    print(f"{len(data)} bytes: {data.hex()}")

    # unpackb turns the bytes back into a dict.
    print(f"unpacked: {unpackb(data)}")

    time.sleep(1)
