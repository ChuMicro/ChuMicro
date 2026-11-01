"""Write a reading into a stream with ``pack`` and read it back with ``unpack``.

``pack(reading, stream)`` writes msgpack bytes into anything that has a
``write()`` method: a file, a network socket, or, in this example, a
``BytesIO``, which acts like a file kept in memory.  ``unpack(stream)`` reads
them back.  Every second the board packs a new reading into a fresh stream,
prints how many bytes went in, rewinds the stream to the start, and unpacks
the reading again.

On a CircuitPython board these are the firmware's own ``msgpack.pack`` and
``msgpack.unpack``, so code written against them runs the same there as on
MicroPython or a laptop.

Setup:

1. Install the library.  On CircuitPython run
   ``circup install chumicro_msgpack``; on MicroPython run
   ``mpremote mip install github:ChuMicro/ChuMicro-Bundle/chumicro_msgpack``.
2. No wiring needed.
3. Save this file as ``code.py`` (CircuitPython) or ``main.py``
   (MicroPython) on the board.

Example output::

    wrote 20 bytes
    read back: {'count': 1, 'temp_c': 20.5}
    wrote 20 bytes
    read back: {'count': 2, 'temp_c': 21.0}

Runs on CPython, MicroPython, and CircuitPython.
"""

import time
from io import BytesIO

from chumicro_msgpack import pack, unpack

count = 0

while True:
    count += 1
    # A pretend temperature that climbs from 20.0 to 24.5 and starts over.
    reading = {"count": count, "temp_c": 20.0 + (count % 10) / 2}

    # pack writes the reading into the stream as msgpack bytes.
    stream = BytesIO()
    pack(reading, stream)
    print(f"wrote {stream.tell()} bytes")

    # Rewind to the start, then unpack reads the reading back out.
    stream.seek(0)
    print(f"read back: {unpack(stream)}")

    time.sleep(1)
