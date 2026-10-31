"""Measure the same reading as JSON and as msgpack, every two seconds.

Every two seconds the board takes a pretend sensor reading and prints how
many bytes it takes three ways: as JSON text, as msgpack with the usual
string keys, and as msgpack with small numbers in place of the key names.
msgpack comes out smaller than JSON, and number keys shrink it further: each
one fits in a single byte, where the key "humidity" takes nine.  Smaller
data means more readings fit in a board's memory and each message sends
faster.

Setup:

1. Install the library.  On CircuitPython run
   ``circup install chumicro_msgpack``; on MicroPython run
   ``mpremote mip install github:ChuMicro/ChuMicro-Bundle/chumicro_msgpack``.
2. No wiring needed.
3. Save this file as ``code.py`` (CircuitPython) or ``main.py``
   (MicroPython) on the board.

Example output::

    reading 1: JSON 64 bytes, msgpack 41 bytes, msgpack with number keys 13 bytes
    reading 2: JSON 63 bytes, msgpack 41 bytes, msgpack with number keys 13 bytes
    reading 3: JSON 64 bytes, msgpack 41 bytes, msgpack with number keys 13 bytes

Runs on CPython, MicroPython, and CircuitPython.
"""

import json
import time

from chumicro_msgpack import packb

# Number keys for the same four fields.  Named constants keep the code
# readable while the packed data stays small.
COUNT = 0
TEMP_C = 1
HUMIDITY = 2
DOOR_OPEN = 3

count = 0

while True:
    count += 1

    # A pretend reading that changes a little every time.
    temp_c = 20.0 + (count % 10) / 2
    humidity = 40 + count % 20
    door_open = count % 2 == 0

    with_names = {
        "count": count,
        "temp_c": temp_c,
        "humidity": humidity,
        "door_open": door_open,
    }
    with_numbers = {
        COUNT: count,
        TEMP_C: temp_c,
        HUMIDITY: humidity,
        DOOR_OPEN: door_open,
    }

    json_size = len(json.dumps(with_names))
    msgpack_size = len(packb(with_names))
    number_keys_size = len(packb(with_numbers))

    print(
        f"reading {count}: JSON {json_size} bytes, msgpack {msgpack_size} bytes, "
        f"msgpack with number keys {number_keys_size} bytes"
    )

    time.sleep(2)
